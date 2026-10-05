import json, os, pathlib, shutil, subprocess, tempfile, traceback
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from .db import SessionLocal
from .models import Project,DatasetFile,ProcessingJob,LidarBlock,Pole,Finding,SceneFeature,AuditLog,ProductionAnnotation
from .workflow import DatasetVersion, QCRun, version_files, record_findings_for_run, complete_qc_run, archive_review_decisions
from .storage import MODE, local_path, download_to, upload_from, read_bytes, object_exists
from pyproj import Transformer
from .ingest import parse_workbook
from .geojson_import import GeoJSONError, import_project_geojson, summary_message
from .sections import generate_lidar_section


def utcnow(): return datetime.now(timezone.utc)

def run(cmd):
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if p.returncode!=0: raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{p.stderr or p.stdout}")
    return p.stdout

def pdal_exe(): return os.getenv('PDAL_BIN','pdal')

def pdal_summary(path):
    return json.loads(run([pdal_exe(),'info',str(path),'--summary']))['summary']

def to_copc(src,dst,crs):
    s=str(src).lower()
    if s.endswith('.copc.laz'):
        shutil.copy2(src,dst); return
    cmd=[pdal_exe(),'translate',str(src),str(dst),'--reader','readers.las','--writer','writers.copc','--writers.copc.forward=all']
    # Source exports from TerraScan often omit SRS; default_srs assigns metadata without reprojecting.
    cmd.append(f'--readers.las.default_srs={crs}')
    run(cmd)

def setjob(db,job,progress,stage,message=None):
    job.progress=progress; job.stage=stage; job.message=message; db.commit()

def process_job(job_id:str):
    probe=SessionLocal(); probe_job=probe.query(ProcessingJob).filter_by(id=job_id).first(); job_type=(probe_job.job_type if probe_job else None); probe.close()
    if job_type == 'SECTION':
        return process_section_job(job_id)
    db=SessionLocal(); job=db.query(ProcessingJob).filter_by(id=job_id).first()
    if not job: db.close(); return
    project=db.query(Project).filter_by(id=job.project_id).first()
    lidar_only=job.job_type=='LIDAR_INGEST'
    payload=json.loads(job.payload_json or '{}')
    version_id=payload.get('version_id'); qc_run_id=payload.get('qc_run_id')
    if qc_run_id:
        runrow=db.query(QCRun).filter_by(id=qc_run_id).first()
        if runrow: runrow.status='RUNNING'; runrow.started_at=utcnow()
    job.status='RUNNING'; job.started_at=utcnow(); db.commit()
    tmp=pathlib.Path(tempfile.mkdtemp(prefix=f'pla-{project.id}-'))
    try:
        files=version_files(db,version_id) if version_id else db.query(DatasetFile).filter_by(project_id=project.id).all()
        workbook=next((f for f in reversed(files) if f.role=='WORKBOOK' and f.status=='UPLOADED'),None)
        lidar=[f for f in files if f.role=='LIDAR_SOURCE' and f.status=='UPLOADED']
        geojson=next((f for f in reversed(files) if f.role=='GEOJSON' and f.status=='UPLOADED'),None)
        if not workbook and not lidar_only: raise RuntimeError('No uploaded workbook is available')
        if not lidar: raise RuntimeError('No LAS/LAZ/COPC LiDAR files are uploaded')

        setjob(db,job,5,'Preparing source files')
        # In local mode read the uploaded workbook/LiDAR in-place to avoid duplicating multi-GB files.
        wbpath = local_path(workbook.object_key) if workbook and MODE == 'local' else (tmp/workbook.filename if workbook else None)
        if workbook and MODE != 'local':
            download_to(workbook.object_key,str(wbpath))

        version=db.query(DatasetVersion).filter_by(id=version_id).first() if version_id else None
        lidar_prefix=f'{project.id}/versions/v{version.version_no}/lidar' if version else f'{project.id}/lidar'
        blocks=[]
        # Reuse COPC already converted for the same source file (e.g. by Production) instead of converting again.
        # Plain column rows, not ORM objects: the old blocks are bulk-deleted and re-inserted below.
        converted={b.source_object_key:b for b in db.query(LidarBlock.source_object_key,LidarBlock.name,LidarBlock.object_key,LidarBlock.point_count,LidarBlock.x_min,LidarBlock.y_min,LidarBlock.x_max,LidarBlock.y_max,LidarBlock.zmin,LidarBlock.zmax).filter(LidarBlock.project_id==project.id).all() if b.source_object_key}
        for idx,f in enumerate(lidar,1):
            previous=converted.get(f.object_key)
            if previous and object_exists(previous.object_key):
                setjob(db,job,5+int(50*(idx-1)/max(1,len(lidar))),f'Reusing converted LiDAR {idx}/{len(lidar)}: {f.filename}')
                blocks.append({'name':previous.name,'source_object_key':f.object_key,'object_key':previous.object_key,'point_count':previous.point_count,
                    'x_min':previous.x_min,'y_min':previous.y_min,'x_max':previous.x_max,'y_max':previous.y_max,'zmin':previous.zmin,'zmax':previous.zmax})
                continue
            setjob(db,job,5+int(50*(idx-1)/max(1,len(lidar))),f'Converting LiDAR {idx}/{len(lidar)}: {f.filename}')
            stem=f.filename[:-9] if f.filename.lower().endswith('.copc.laz') else pathlib.Path(f.filename).stem

            if MODE == 'local':
                src = local_path(f.object_key)
                # Reuse already-COPC uploads directly. LAS/LAZ are converted once into the canonical lidar folder.
                if f.filename.lower().endswith('.copc.laz'):
                    out = src
                    key = f.object_key
                else:
                    key=f'{lidar_prefix}/{stem}.copc.laz'
                    out=local_path(key)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    if not out.exists():
                        to_copc(src,out,project.crs)
            else:
                src=tmp/f.filename; download_to(f.object_key,str(src))
                out=tmp/f'{stem}.copc.laz'
                to_copc(src,out,project.crs)
                key=f'{lidar_prefix}/{out.name}'
                upload_from(str(out),key,'application/octet-stream')

            summ=pdal_summary(out); b=summ['bounds']
            blocks.append({'name':stem,'source_object_key':f.object_key,'object_key':key,'point_count':summ.get('num_points'),
                'x_min':b['minx'],'y_min':b['miny'],'x_max':b['maxx'],'y_max':b['maxy'],'zmin':b.get('minz'),'zmax':b.get('maxz')})

        if lidar_only:
            setjob(db,job,85,'Publishing LiDAR catalogue')
            db.query(LidarBlock).filter_by(project_id=project.id).delete(); db.flush()
            for block in blocks: db.add(LidarBlock(project_id=project.id,poles_json='[]',**block))
            imported_poles=0; pole_changes=None
            if workbook:
                setjob(db,job,90,'Importing Production pole catalogue')
                parsed=parse_workbook(str(wbpath),project.crs)
                tf=Transformer.from_crs('EPSG:4326',project.crs,always_xy=True)
                existing={p.internal_id:p for p in db.query(Pole).filter_by(project_id=project.id).all()}
                poles_by_block={b['name']:[] for b in blocks}
                for source in parsed['poles']:
                    block_name=None
                    if source.get('corrected_lat') is not None and source.get('corrected_lon') is not None:
                        x,y=tf.transform(float(source['corrected_lon']),float(source['corrected_lat']))
                        candidate=next((b for b in blocks if b['x_min']<=x<=b['x_max'] and b['y_min']<=y<=b['y_max']),None)
                        if candidate:
                            block_name=candidate['name']; poles_by_block[block_name].append(source['internal_id'])
                    pole=existing.get(source['internal_id'])
                    if not pole:
                        pole=Pole(project_id=project.id,internal_id=source['internal_id']); db.add(pole)
                    pole.pole_number=source['pole_number']; pole.block_name=block_name
                    pole.corrected_lat=source['corrected_lat']; pole.corrected_lon=source['corrected_lon']
                    pole.bottom_elev_ft=source['bottom_elev_ft']; pole.top_elev_ft=source['top_elev_ft']
                    pole.remarks=source['remarks']; pole.manifest_json=json.dumps(source['manifest'],default=str)
                    imported_poles+=1
                # After a workbook replacement, poles only in the previous workbook are removed unless Production work references them.
                current_ids={source['internal_id'] for source in parsed['poles']}
                stale=[pole for internal_id,pole in existing.items() if internal_id not in current_ids]
                if stale:
                    annotated={row[0] for row in db.query(ProductionAnnotation.pole_internal_id).filter(ProductionAnnotation.project_id==project.id,ProductionAnnotation.pole_internal_id.in_([p.internal_id for p in stale])).all()}
                    kept=[p for p in stale if p.internal_id in annotated or p.verified_annotation_id or p.verified_bottom_annotation_id or p.verified_top_annotation_id]
                    for pole in stale:
                        if pole not in kept: db.delete(pole)
                    pole_changes={'removed':len(stale)-len(kept),'kept_with_production_work':[p.pole_number or str(p.internal_id) for p in kept]}
                for row in db.query(LidarBlock).filter_by(project_id=project.id).all(): row.poles_json=json.dumps(poles_by_block.get(row.name,[]))
                project.source_workbook_key=workbook.object_key
            geo_summary=None
            if geojson:
                setjob(db,job,95,'Importing client GeoJSON')
                db.flush()
                # A rejected GeoJSON is reported, not fatal: the converted LiDAR and workbook poles stay usable.
                try:
                    geo_summary=import_project_geojson(db,project,geojson.id,read_bytes(geojson.object_key))
                    job.message=summary_message(geo_summary)
                except GeoJSONError as exc:
                    geo_summary={'error':str(exc)}; job.message=f'GeoJSON rejected: {exc}'
            if pole_changes:
                kept=pole_changes['kept_with_production_work']
                note=f"Workbook replaced: {imported_poles} poles imported, {pole_changes['removed']} removed"+(f", {len(kept)} kept because they have saved points or verification ({', '.join(kept[:10])})" if kept else "")
                job.message=f'{note} · {job.message}' if job.message else note
            if version: version.status='LIDAR_READY'
            project.status='LIDAR_READY'
            job.status='SUCCEEDED'; job.progress=100; job.stage='LiDAR ready'; job.finished_at=utcnow()
            db.add(AuditLog(actor='worker',action='PROCESS_LIDAR',entity_type='project',entity_id=project.id,detail_json=json.dumps({'blocks':len(blocks),'poles':imported_poles,'version_id':version_id,'geojson':geo_summary,'workbook_replacement':pole_changes})))
            db.commit(); return

        setjob(db,job,60,'Parsing workbook and building 3D delivery geometry')
        parsed=parse_workbook(str(wbpath),project.crs)

        # Preserve reviewer history, then replace project-derived state atomically.
        archived_decisions=archive_review_decisions(db,project.id)
        db.query(SceneFeature).filter_by(project_id=project.id).delete(); db.query(Finding).filter_by(project_id=project.id).delete(); db.query(LidarBlock).filter_by(project_id=project.id).delete(); db.flush()
        # Poles are updated in place, not recreated, so LiDAR verification captured in Production survives QC processing.
        existing_poles={p.internal_id:p for p in db.query(Pole).filter_by(project_id=project.id).all()}
        for b in blocks: db.add(LidarBlock(project_id=project.id,poles_json='[]',**b))
        db.flush()

        # Map poles to LiDAR using complete 3D delivery geometry when available.
        # If Z/top geometry is still blank (common in pre-populated field workbooks), fall back to
        # the available source/pre-pop latitude+longitude so reviewers can still open the correct
        # LiDAR block and generate profile evidence.
        pole_feature={int(f['properties']['internal_id']):f for f in parsed['features'] if f['properties'].get('feature_type')=='pole'}
        poles_by_block={b['name']:[] for b in blocks}
        tf = Transformer.from_crs('EPSG:4326', project.crs, always_xy=True)
        for p in parsed['poles']:
            pf=pole_feature.get(p['internal_id']); block=None; x=y=None
            if pf:
                x,y=pf['geometry']['coordinates'][0][:2]
            elif p.get('corrected_lat') is not None and p.get('corrected_lon') is not None:
                x,y=tf.transform(float(p['corrected_lon']), float(p['corrected_lat']))
            if x is not None and y is not None:
                candidates=[b for b in blocks if b['x_min']<=x<=b['x_max'] and b['y_min']<=y<=b['y_max']]
                if candidates:
                    block=candidates[0]['name']; poles_by_block[block].append(p['internal_id'])
            pole=existing_poles.pop(p['internal_id'],None)
            if not pole:
                pole=Pole(project_id=project.id,internal_id=p['internal_id']); db.add(pole)
            pole.pole_number=p['pole_number']; pole.block_name=block
            pole.corrected_lat=p['corrected_lat']; pole.corrected_lon=p['corrected_lon']
            pole.bottom_elev_ft=p['bottom_elev_ft']; pole.top_elev_ft=p['top_elev_ft']
            pole.remarks=p['remarks']; pole.manifest_json=json.dumps(p['manifest'],default=str)
        for stale in existing_poles.values():
            # A pole removed from the workbook is dropped unless Production already verified it in the LiDAR.
            if not (stale.verified_annotation_id or stale.verified_bottom_annotation_id or stale.verified_top_annotation_id): db.delete(stale)
        for b in db.query(LidarBlock).filter_by(project_id=project.id).all(): b.poles_json=json.dumps(poles_by_block.get(b.name,[]))
        db.flush()
        geo_summary=None
        if geojson:
            # Optional GeoJSON attached to a QC dataset is matched to the QC workbook poles; a bad file is reported, not fatal.
            try:
                geo_summary=import_project_geojson(db,project,geojson.id,read_bytes(geojson.object_key)); job.message=summary_message(geo_summary)
            except GeoJSONError as exc:
                geo_summary={'error':str(exc)}; job.message=f'GeoJSON rejected: {exc}'
            db.flush()

        # Findings and per-pole status
        for f in parsed['findings']:
            db.add(Finding(project_id=project.id,related_poles_json=json.dumps(f.pop('related_poles')),**f))
        for feat in parsed['features']:
            db.add(SceneFeature(project_id=project.id,internal_id=int(feat['properties']['internal_id']),feature_type=feat['properties']['feature_type'],payload_json=json.dumps(feat)))
        db.flush()
        counts={}
        for f in db.query(Finding).filter_by(project_id=project.id).all():
            c=counts.setdefault(f.internal_id,{'FAIL':0,'REVIEW':0,'UNVERIFIABLE':0}); c[f.severity]=c.get(f.severity,0)+1
        for p in db.query(Pole).filter_by(project_id=project.id).all():
            c=counts.get(p.internal_id,{}); p.qc_fail=c.get('FAIL',0); p.qc_review=c.get('REVIEW',0); p.qc_unverifiable=c.get('UNVERIFIABLE',0)
            p.qc_status='FAIL' if p.qc_fail else ('REVIEW' if p.qc_review else ('UNVERIFIABLE' if p.qc_unverifiable else 'PASS'))
        comparison={}
        if version_id and qc_run_id:
            comparison=record_findings_for_run(db,project.id,version_id,qc_run_id)
            complete_qc_run(db,qc_run_id,True,{'blocks':len(blocks),'poles':len(parsed['poles']),'findings':len(parsed['findings']),'comparison':comparison})
        project.source_workbook_key=workbook.object_key; project.status='READY_FOR_QC'
        job.status='SUCCEEDED'; job.progress=100; job.stage='Ready for QC'; job.finished_at=utcnow();
        db.add(AuditLog(actor='worker',action='PROCESS_DATASET',entity_type='project',entity_id=project.id,detail_json=json.dumps({'blocks':len(blocks),'poles':len(parsed['poles']),'findings':len(parsed['findings']),'version_id':version_id,'qc_run_id':qc_run_id,'comparison':comparison,'archived_decisions':archived_decisions})))
        db.commit()
    except Exception as e:
        db.rollback(); job=db.query(ProcessingJob).filter_by(id=job_id).first(); project=db.query(Project).filter_by(id=job.project_id).first() if job else None
        if job:
            job.status='FAILED'; job.stage='Failed'; job.error=f'{e}\n{traceback.format_exc()}'; job.finished_at=utcnow()
        if project: project.status='FAILED'
        if qc_run_id: complete_qc_run(db,qc_run_id,False,{'error':str(e)[:1000]})
        db.commit()
    finally:
        shutil.rmtree(tmp,ignore_errors=True); db.close()


def process_section_job(job_id:str):
    db=SessionLocal(); job=db.query(ProcessingJob).filter_by(id=job_id).first()
    if not job: db.close(); return
    job.status='RUNNING'; job.started_at=utcnow(); db.commit()
    try:
        payload=json.loads(job.payload_json or '{}')
        setjob(db,job,10,'Preparing synchronized profile frame')
        key=generate_lidar_section(
            db, job.project_id, int(payload['internal_id']), payload.get('target_internal_id'),
            float(payload.get('width',12.0)), float(payload.get('depth',12.0)),
            float(payload.get('resolution',0.5)), int(payload.get('max_points',90000))
        )
        job.result_key=key; job.status='SUCCEEDED'; job.progress=100; job.stage='Profile / section ready'; job.finished_at=utcnow()
        db.add(AuditLog(actor='worker',action='GENERATE_SECTION',entity_type='project',entity_id=job.project_id,detail_json=json.dumps({'result_key':key,**payload})))
        db.commit()
    except Exception as e:
        db.rollback(); job=db.query(ProcessingJob).filter_by(id=job_id).first()
        if job:
            job.status='FAILED'; job.stage='Failed'; job.error=f'{e}\n{traceback.format_exc()}'; job.finished_at=utcnow(); db.commit()
    finally:
        db.close()
