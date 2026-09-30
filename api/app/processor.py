import json, os, pathlib, shutil, subprocess, tempfile, traceback
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from .db import SessionLocal
from .models import Project,DatasetFile,ProcessingJob,LidarBlock,Pole,Finding,SceneFeature,AuditLog
from .workflow import DatasetVersion, QCRun, version_files, record_findings_for_run, complete_qc_run, archive_review_decisions
from .storage import MODE, local_path, download_to, upload_from
from pyproj import Transformer
from .ingest import parse_workbook
from .sections import generate_lidar_section
from .v4_ingest import build_source_records
from .v4_domain import SourceRecord, EngineeringAsset


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
        if not workbook: raise RuntimeError('No uploaded workbook is available')
        if not lidar: raise RuntimeError('No LAS/LAZ/COPC LiDAR files are uploaded')

        setjob(db,job,5,'Preparing source files')
        # In local mode read the uploaded workbook/LiDAR in-place to avoid duplicating multi-GB files.
        wbpath = local_path(workbook.object_key) if MODE == 'local' else (tmp/workbook.filename)
        if MODE != 'local':
            download_to(workbook.object_key,str(wbpath))

        version=db.query(DatasetVersion).filter_by(id=version_id).first() if version_id else None
        lidar_prefix=f'{project.id}/versions/v{version.version_no}/lidar' if version else f'{project.id}/lidar'
        blocks=[]
        for idx,f in enumerate(lidar,1):
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

        setjob(db,job,60,'Parsing workbook and building 3D delivery geometry')
        parsed=parse_workbook(str(wbpath),project.crs)

        # v4 canonical source layer: preserve every non-empty pole source row, including
        # records intentionally left without internal_id. This runs alongside the legacy
        # v3.4 projection while the platform/v4.0 branch is validated in staging.
        snapshot_id = version_id or f"JOB-{job.id}"
        db.query(EngineeringAsset).filter_by(project_id=project.id, snapshot_id=snapshot_id).delete()
        db.query(SourceRecord).filter_by(project_id=project.id, snapshot_id=snapshot_id).delete()
        for source in build_source_records(project.id, snapshot_id, str(wbpath), "poles"):
            db.add(SourceRecord(**source))
            payload_source = json.loads(source["source_payload_json"])
            raw_id = payload_source.get("internal_id")
            try:
                canonical_internal_id = int(float(raw_id)) if raw_id not in (None, "") else None
            except (TypeError, ValueError):
                canonical_internal_id = None
            db.add(EngineeringAsset(
                id=f"AST-{source['id'][4:]}",
                project_id=project.id,
                snapshot_id=snapshot_id,
                source_record_id=source["id"],
                asset_type="POLE",
                pole_number=source.get("pole_number"),
                internal_id=canonical_internal_id,
                production_state="IMPORTED",
                evidence_state="UNASSESSED",
                qc_state="NOT_REVIEWED",
                release_state="NOT_ELIGIBLE",
                remarks=payload_source.get("remarks"),
            ))
        db.flush()

        # Preserve reviewer history, then replace project-derived state atomically.
        archived_decisions=archive_review_decisions(db,project.id)
        db.query(SceneFeature).filter_by(project_id=project.id).delete(); db.query(Finding).filter_by(project_id=project.id).delete(); db.query(Pole).filter_by(project_id=project.id).delete(); db.query(LidarBlock).filter_by(project_id=project.id).delete(); db.flush()
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
            db.add(Pole(project_id=project.id,internal_id=p['internal_id'],pole_number=p['pole_number'],block_name=block,
                corrected_lat=p['corrected_lat'],corrected_lon=p['corrected_lon'],bottom_elev_ft=p['bottom_elev_ft'],top_elev_ft=p['top_elev_ft'],remarks=p['remarks'],manifest_json=json.dumps(p['manifest'],default=str)))
        for b in db.query(LidarBlock).filter_by(project_id=project.id).all(): b.poles_json=json.dumps(poles_by_block.get(b.name,[]))
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
