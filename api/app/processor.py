import json, math, os, pathlib, shutil, subprocess, tempfile, traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from .db import SessionLocal
from .models import Project,DatasetFile,ProcessingJob,LidarBlock,Pole,Finding,SceneFeature,AuditLog,ProductionAnnotation,ProductionGeoFeature
from .notifications import notify_qc_finished, safely
from .workflow import DatasetVersion, QCRun, version_files, record_findings_for_run, complete_qc_run, archive_review_decisions
from .storage import MODE, local_path, download_to, upload_from, read_bytes, object_exists
from pyproj import Transformer
from .ingest import make_finding, parse_workbook, rule_status
from .geojson_import import GeoJSONError, _is_feet, import_project_geojson, match_tolerances, summary_message
from .sections import generate_lidar_section


def utcnow(): return datetime.now(timezone.utc)

def _low_priority():
    """Run heavy PDAL work below normal priority so the desktop/API stay responsive while it converts."""
    if os.name=='nt': return {'creationflags':getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0x4000)}
    return {'preexec_fn':lambda: os.nice(10)}

def run(cmd,*,low_priority=False):
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,**(_low_priority() if low_priority else {}))
    if p.returncode!=0:
        detail=(p.stderr or p.stdout).strip() or (f'PDAL exited with code {p.returncode} and no message; '
            'this usually means it ran out of memory or disk space')
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{detail}")
    return p.stdout

def pdal_exe(): return os.getenv('PDAL_BIN','pdal')

def pdal_summary(path):
    return json.loads(run([pdal_exe(),'info',str(path),'--summary']))['summary']

def untwine_exe():
    """Untwine builds COPC out-of-core on all cores: measured 43 s / 1.3 GB RAM for 82.5M points, where PDAL's
    single-threaded writers.copc took 687 s / 9.5 GB. Used when installed; PDAL stays the fallback."""
    configured=os.getenv('UNTWINE_BIN')
    if configured: return configured if pathlib.Path(configured).exists() or shutil.which(configured) else None
    found=shutil.which('untwine')
    if found: return found
    pdal=shutil.which(pdal_exe()) or pdal_exe()
    sibling=pathlib.Path(pdal).with_name('untwine.exe' if os.name=='nt' else 'untwine')
    return str(sibling) if sibling.exists() else None

def to_copc(src,dst,crs):
    s=str(src).lower()
    if s.endswith('.copc.laz'):
        shutil.copy2(src,dst); return
    # Write beside the target and rename when finished, so an interrupted run never leaves a
    # truncated COPC that a later run would mistake for a finished conversion.
    partial=pathlib.Path(f'{dst}.partial')
    untwine=untwine_exe()
    try:
        if untwine:
            work=pathlib.Path(tempfile.mkdtemp(prefix='.untwine-',dir=pathlib.Path(dst).parent))
            try:
                cmd=[untwine,'-i',str(src),'-o',str(partial),'--temp_dir',str(work)]
                # Same rule as PDAL's default_srs: assign the project CRS only when the file has none (no reprojection).
                if not lidar_has_srs(src): cmd+=['--a_srs',crs]
                run(cmd,low_priority=True)
            finally:
                shutil.rmtree(work,ignore_errors=True)  # untwine leaves its scratch files behind (~65 bytes/point)
        else:
            cmd=[pdal_exe(),'translate',str(src),str(partial),'--reader','readers.las','--writer','writers.copc','--writers.copc.forward=all',
                 # Source exports from TerraScan often omit SRS; default_srs assigns metadata without reprojecting.
                 f'--readers.las.default_srs={crs}',f'--writers.copc.threads={max(1,min(16,os.cpu_count() or 1))}']
            run(cmd,low_priority=True)
        os.replace(partial,dst)
    finally:
        partial.unlink(missing_ok=True)

def lidar_workers():
    """Upper bound on parallel LAS/LAZ conversions; the memory and disk budgets usually decide the real number."""
    try: configured=int(os.getenv('LIDAR_CONVERT_WORKERS','0'))
    except ValueError: configured=0
    if configured>0: return configured
    # Untwine already uses every core, so two at a time is enough; PDAL's writer is mostly single-threaded.
    return 2 if untwine_exe() else max(1,min(4,(os.cpu_count() or 2)//2))

GB=1024**3

def copc_bytes_per_point():
    """Peak RAM per point while building COPC. Measured: PDAL writers.copc ~120 B (82.5M points -> 9.5 GB);
    untwine ~16 B (82.5M points -> 1.3 GB), rounded up to 24."""
    try:
        configured=int(os.getenv('LIDAR_COPC_BYTES_PER_POINT','0'))
        if configured>0: return configured
    except ValueError: pass
    return 24 if untwine_exe() else 120

def copc_temp_bytes_per_point():
    """Scratch disk per point: untwine spills ~65 B/point to its temp folder; PDAL works in memory."""
    return 70 if untwine_exe() else 0

def available_memory():
    """Bytes of RAM free for new work (Windows, or Linux including a container memory limit); None if unknown."""
    try:
        if os.name=='nt':
            import ctypes
            class Status(ctypes.Structure):
                _fields_=[('dwLength',ctypes.c_ulong),('dwMemoryLoad',ctypes.c_ulong),('ullTotalPhys',ctypes.c_ulonglong),('ullAvailPhys',ctypes.c_ulonglong),
                          ('ullTotalPageFile',ctypes.c_ulonglong),('ullAvailPageFile',ctypes.c_ulonglong),('ullTotalVirtual',ctypes.c_ulonglong),
                          ('ullAvailVirtual',ctypes.c_ulonglong),('ullAvailExtendedVirtual',ctypes.c_ulonglong)]
            status=Status(); status.dwLength=ctypes.sizeof(Status)
            return int(status.ullAvailPhys) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else None
        free=None
        with open('/proc/meminfo') as fh:
            for line in fh:
                if line.startswith('MemAvailable:'): free=int(line.split()[1])*1024
        try:
            limit=pathlib.Path('/sys/fs/cgroup/memory.max').read_text().strip()
            used=int(pathlib.Path('/sys/fs/cgroup/memory.current').read_text())
            if limit!='max': free=min(free if free is not None else int(limit),int(limit)-used)
        except (OSError,ValueError): pass
        return free
    except Exception:
        return None

def memory_budget():
    """RAM the conversions may use together: LIDAR_MEMORY_BUDGET_GB, else 70% of what is free when the job starts."""
    try:
        configured=float(os.getenv('LIDAR_MEMORY_BUDGET_GB','0'))
        if configured>0: return int(configured*GB)
    except ValueError: pass
    free=available_memory()
    return int(free*0.7) if free else None

def lidar_header(path):
    """Point count and bounds from the LAS/LAZ header only (fast, no points are read)."""
    meta=json.loads(run([pdal_exe(),'info','--metadata',str(path)]))['metadata']
    return {'count':int(meta['count']),**{k:float(meta[k]) for k in ('minx','maxx','miny','maxy')}}

def lidar_has_srs(path):
    """True when the LAS/LAZ header carries a spatial reference (unreadable headers count as missing)."""
    try:
        meta=json.loads(run([pdal_exe(),'info','--metadata',str(path)]))['metadata']
        srs=meta.get('srs') or {}
        return bool(srs.get('wkt') or srs.get('horizontal') or meta.get('comp_spatialreference') or meta.get('spatialreference'))
    except Exception:
        return False

def lidar_point_count(path):
    """Point count from the LAS/LAZ header only (fast); None if it cannot be read."""
    try: return lidar_header(path)['count']
    except Exception: return None

def conversion_cost(f,lidar_prefix):
    """(RAM bytes, disk bytes) one file's conversion needs; (0, 0) when nothing has to be converted."""
    name=f['filename'].lower(); size=int(f.get('size_bytes') or 0)
    if name.endswith('.copc.laz'): return 0,0
    points=None
    if MODE=='local':
        if local_path(f"{lidar_prefix}/{lidar_stem(f['filename'])}.copc.laz").exists(): return 0,0
        points=lidar_point_count(local_path(f['object_key']))
    if points is None:  # LAZ exports store ~4.2 bytes per point, LAS ~30-38.
        points=size//4 if name.endswith('.laz') else size//30
    # COPC output is about LAZ-sized (~5 B/point) plus untwine's scratch; bucket mode also holds the downloaded source.
    disk=int(points*(5*1.2+copc_temp_bytes_per_point()))+256*1024**2+(size if MODE!='local' else 0)
    return points*copc_bytes_per_point(),disk

def _gb(value): return f'{value/GB:.1f} GB'

def lidar_stem(filename):
    return filename[:-9] if filename.lower().endswith('.copc.laz') else pathlib.Path(filename).stem

def _block(name,key,summ):
    b=summ['bounds']
    return {'name':name,'object_key':key,'point_count':summ.get('num_points'),
        'x_min':b['minx'],'y_min':b['miny'],'x_max':b['maxx'],'y_max':b['maxy'],'zmin':b.get('minz'),'zmax':b.get('maxz')}

def convert_lidar_file(f,lidar_prefix,crs,tmp):
    """Convert one uploaded LAS/LAZ (or adopt a COPC upload) and return its block row. Safe to run in a thread."""
    stem=lidar_stem(f['filename'])
    if MODE == 'local':
        src = local_path(f['object_key'])
        # Reuse already-COPC uploads directly. LAS/LAZ are converted once into the canonical lidar folder.
        if f['filename'].lower().endswith('.copc.laz'):
            out = src
            key = f['object_key']
        else:
            key=f'{lidar_prefix}/{stem}.copc.laz'
            out=local_path(key)
            out.parent.mkdir(parents=True, exist_ok=True)
            if not out.exists():
                to_copc(src,out,crs)
        summ=pdal_summary(out)
    else:
        work=tmp/f['id']; work.mkdir(parents=True,exist_ok=True)
        src=work/f['filename']; download_to(f['object_key'],str(src))
        out=work/f'{stem}.copc.laz'
        try:
            to_copc(src,out,crs)
            key=f'{lidar_prefix}/{out.name}'
            upload_from(str(out),key,'application/octet-stream')
            summ=pdal_summary(out)
        finally:
            # Several multi-GB files convert at once; free each one's disk as soon as it is uploaded.
            shutil.rmtree(work,ignore_errors=True)
    return _block(stem,key,summ)

def convert_lidar_part(part,name,lidar_prefix,crs):
    """Convert one split piece (a temporary LAZ) into its own COPC block, then delete the piece."""
    key=f'{lidar_prefix}/{name}.copc.laz'
    try:
        if MODE == 'local':
            out=local_path(key); out.parent.mkdir(parents=True,exist_ok=True)
            if not out.exists(): to_copc(part,out,crs)
            return _block(name,key,pdal_summary(out))
        out=part.with_name(f'{name}.copc.laz')
        try:
            to_copc(part,out,crs)
            upload_from(str(out),key,'application/octet-stream')
            return _block(name,key,pdal_summary(out))
        finally: out.unlink(missing_ok=True)
    finally:
        part.unlink(missing_ok=True)

def _halve(src,header,crs,workdir,label):
    """Cut a tile in two along its longer side with streaming PDAL range filters (low memory, every point kept)."""
    axes=['X','Y'] if header['maxx']-header['minx']>=header['maxy']-header['miny'] else ['Y','X']
    for axis in axes:
        lo,hi=(header['minx'],header['maxx']) if axis=='X' else (header['miny'],header['maxy'])
        mid=(lo+hi)/2
        outs=[workdir/f'{label}a.laz',workdir/f'{label}b.laz']
        # Open outer edges so no point is lost to header rounding; [lo:mid) and [mid:] never overlap.
        limits=[f'{axis}[:{mid!r})',f'{axis}[{mid!r}:]']
        def crop(index):
            run([pdal_exe(),'translate',str(src),str(outs[index]),'-f','filters.range',f'--filters.range.limits={limits[index]}',
                 '--writers.las.forward=all',f'--readers.las.default_srs={crs}'],low_priority=True)
            return lidar_header(outs[index])
        with ThreadPoolExecutor(max_workers=2,thread_name_prefix='lidar-split') as pool:
            halves=list(pool.map(crop,[0,1]))
        if sum(h['count'] for h in halves)!=header['count']:
            for out in outs: out.unlink(missing_ok=True)
            raise RuntimeError(f'Splitting {src.name} lost points ({sum(h["count"] for h in halves)} of {header["count"]}); nothing was imported')
        if all(h['count'] for h in halves):
            return list(zip(outs,halves))
        for out in outs: out.unlink(missing_ok=True)  # everything on one side; try the other axis
    raise RuntimeError(f'{src.name} cannot be split any further: its points share one location')

def split_lidar_tile(src,crs,workdir,max_points,label='p',depth=0):
    """Halve a tile until every piece has at most max_points. Returns [(laz_path, header)] in a stable order."""
    header=lidar_header(src)
    if header['count']<=max_points: return [(pathlib.Path(src),header)]
    if depth>=10: raise RuntimeError(f'{pathlib.Path(src).name} could not be split small enough to convert')
    pieces=[]
    for index,(half,_) in enumerate(_halve(pathlib.Path(src),header,crs,workdir,label)):
        found=split_lidar_tile(half,crs,workdir,max_points,f'{label}{"ab"[index]}',depth+1)
        if len(found)>1: half.unlink(missing_ok=True)  # an intermediate half, already cut into smaller pieces
        pieces.extend(found)
    return pieces

def convert_lidar_files(files,lidar_prefix,crs,tmp,progress,workers=None,*,budget=None,disk_root=None):
    """Convert files in parallel within RAM and disk budgets; return blocks in upload order.

    ``progress(done,total,running)`` runs on the caller's thread. Large tiles run alone, and a tile too large for
    memory even alone is first split into pieces (each its own block, named ``<tile>_1``, ``<tile>_2`` ...).
    """
    total=len(files); workers=workers or lidar_workers()
    if not files: return []
    # LAS/LAZ uploads with the same name share one output COPC; convert it once and reuse it for the
    # duplicates (as the sequential loop did), instead of two PDAL processes writing the same file.
    owner={}; jobs=[]
    for index,f in enumerate(files):
        shared=None if f['filename'].lower().endswith('.copc.laz') else lidar_stem(f['filename'])
        if shared is not None and shared in owner: continue
        if shared is not None: owner[shared]=index
        jobs.append(index)
    budget=memory_budget() if budget is None else budget
    disk_root=pathlib.Path(disk_root or (local_path(lidar_prefix) if MODE=='local' else tmp))
    disk_root.mkdir(parents=True,exist_ok=True)

    # A unit is one PDAL conversion: a whole file, or one piece of a file that is too large for memory.
    units=[]
    for i in jobs:
        f=files[i]; ram,disk=conversion_cost(f,lidar_prefix)
        if not (budget and ram>budget):
            units.append({'file':i,'ram':ram,'disk':disk,'run':lambda f=f: convert_lidar_file(f,lidar_prefix,crs,tmp)}); continue
        stem=lidar_stem(f['filename']); work=tmp/f'split-{f["id"]}'; work.mkdir(parents=True,exist_ok=True)
        size=int(f.get('size_bytes') or 0)
        if MODE!='local':
            src=work/f['filename']; download_to(f['object_key'],str(src))
        else:
            src=local_path(f['object_key'])
        free=shutil.disk_usage(work).free
        if free<int(size*1.3)+GB:
            raise RuntimeError(f"Not enough disk space to split {f['filename']}: it needs about {_gb(int(size*1.3)+GB)} "
                               f'and {_gb(free)} is free on {work.anchor}. Free some space and retry.')
        max_points=max(1,int(budget*0.8)//copc_bytes_per_point())
        progress(0,total,[f"{f['filename']} (too large for memory: splitting into pieces)"])
        pieces=split_lidar_tile(src,crs,work,max_points)
        if MODE!='local': pathlib.Path(src).unlink(missing_ok=True)
        for number,(piece,header) in enumerate(pieces,1):
            name=f'{stem}_{number}'
            units.append({'file':i,'ram':header['count']*copc_bytes_per_point(),'disk':int(header['count']*(5*1.2+copc_temp_bytes_per_point()))+256*1024**2,
                          'label':f"{f['filename']} part {number}/{len(pieces)}",
                          'run':lambda piece=piece,name=name: convert_lidar_part(piece,name,lidar_prefix,crs)})

    remaining={i:sum(1 for u in units if u['file']==i) for i in jobs}
    blocks={i:[] for i in jobs}; queue=list(range(len(units))); pending={}
    def label(u): return units[u].get('label') or files[units[u]['file']]['filename']
    with ThreadPoolExecutor(max_workers=max(1,min(workers,len(units))),thread_name_prefix='lidar-copc') as pool:
        def running(): return [label(u) for u in sorted(pending.values())]
        def start_ready():
            while queue and len(pending)<workers:
                u=queue[0]; ram,disk=units[u]['ram'],units[u]['disk']
                busy_ram=sum(units[j]['ram'] for j in pending.values()); busy_disk=sum(units[j]['disk'] for j in pending.values())
                free_disk=shutil.disk_usage(disk_root).free
                if pending and ((budget and busy_ram+ram>budget) or busy_disk+disk>free_disk):
                    return  # wait for a running conversion to free memory/disk; keeps upload order
                if not pending and disk>free_disk:
                    raise RuntimeError(f'Not enough disk space to convert {label(u)}: it needs about {_gb(disk)} '
                                       f'and {_gb(free_disk)} is free on {disk_root.anchor or disk_root}. Free some space and retry.')
                queue.pop(0); pending[pool.submit(units[u]['run'])]=u
        try:
            start_ready()
            progress(0,total,running())
            while pending:
                finished,_=wait(pending,return_when=FIRST_COMPLETED)
                for future in finished:
                    u=pending.pop(future); i=units[u]['file']
                    blocks[i].append((u,future.result())); remaining[i]-=1
                start_ready()
                done=sum(1 for i in range(total) if remaining[_block_index(files,i,owner)]==0)
                progress(done,total,running())
        except BaseException:
            for future in pending: future.cancel()
            raise
    return [{**block,'source_object_key':files[i]['object_key']}
            for i in range(total) for _,block in sorted(blocks[_block_index(files,i,owner)],key=lambda item: item[0])]

def _block_index(files,index,owner):
    filename=files[index]['filename']
    return index if filename.lower().endswith('.copc.laz') else owner[lidar_stem(filename)]

def generic_spatial_checks(db,project,parsed,blocks,pole_xy,pole_block,geojson,geo_summary):
    """GEN-003..006 for any workbook layout: LiDAR coverage and agreement with the GeoJSON. Adds findings to
    ``parsed['findings']`` and returns the rule statuses."""
    sheet=parsed.get('pole_sheet') or 'poles'; units='ft' if _is_feet(project.units) else 'm'
    rules=[rule_status('GEN-003',bool(blocks),None if blocks else 'Not applicable: no LiDAR tiles were processed')]
    for p in parsed['poles'] if blocks else []:
        pid=p['internal_id']
        if pid in pole_xy and not pole_block.get(pid):
            x,y=pole_xy[pid]
            parsed['findings'].append(make_finding('GEN-003','REVIEW',pid,p['pole_number'],sheet,'location',
                'Pole location is outside every LiDAR tile, so there is no point-cloud evidence for it.',f'x={x:.2f}, y={y:.2f}','inside a LiDAR tile'))
    if not geojson or geo_summary is None:
        reason='Not applicable: no GeoJSON was uploaded for this QC dataset'
    elif geo_summary.get('error'):
        reason=f"Not applicable: the GeoJSON was rejected ({geo_summary['error']})"
    else:
        reason=None
    rules+=[rule_status(rule_id,reason is None,reason) for rule_id in ('GEN-004','GEN-005','GEN-006')]
    if reason: return rules
    radius,_=match_tolerances(project.units); by_pole={}
    for row in db.query(ProductionGeoFeature).filter_by(project_id=project.id,geometry_type='Point').all():
        if row.pole_internal_id is not None: by_pole.setdefault(row.pole_internal_id,[]).append(row)
    for p in parsed['poles']:
        pid,pnum=p['internal_id'],p['pole_number']; points=by_pole.get(pid,[])
        if not points:
            parsed['findings'].append(make_finding('GEN-004','REVIEW',pid,pnum,'GeoJSON','pole_number / internal_id',
                'No GeoJSON point matches this pole by Pole Number, Internal ID or position.',None,'one matching GeoJSON point'))
        elif len(points)>1:
            parsed['findings'].append(make_finding('GEN-006','REVIEW',pid,pnum,'GeoJSON','pole_number / internal_id',
                f'{len(points)} GeoJSON points match this pole.',', '.join(f'feature {r.feature_index}' for r in sorted(points,key=lambda r: r.feature_index)),'exactly one GeoJSON point'))
        elif pid in pole_xy and points[0].x is not None and points[0].y is not None:
            distance=math.hypot(points[0].x-pole_xy[pid][0],points[0].y-pole_xy[pid][1])
            if distance>radius:
                parsed['findings'].append(make_finding('GEN-005','REVIEW',pid,pnum,'GeoJSON',points[0].match_property or 'geometry',
                    f'GeoJSON point (feature {points[0].feature_index}) is {distance:.1f} {units} from the workbook location.',f'{distance:.2f} {units}',f'within {radius:g} {units}'))
    return rules

def rule_coverage(rules,findings):
    """Per-rule status for the QC run summary: ran / not applicable, and how many findings each rule produced."""
    counts={}
    for f in findings: counts[f['rule_id']]=counts.get(f['rule_id'],0)+1
    return [{**rule,'findings':counts.get(rule['rule_id'],0)} for rule in rules]

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
        converted={}
        for b in db.query(LidarBlock.source_object_key,LidarBlock.name,LidarBlock.object_key,LidarBlock.point_count,LidarBlock.x_min,LidarBlock.y_min,LidarBlock.x_max,LidarBlock.y_max,LidarBlock.zmin,LidarBlock.zmax).filter(LidarBlock.project_id==project.id).all():
            if b.source_object_key: converted.setdefault(b.source_object_key,[]).append(b)
        to_convert=[]; reused=0
        for idx,f in enumerate(lidar,1):
            previous=converted.get(f.object_key) or []
            if previous and all(object_exists(b.object_key) for b in previous):
                setjob(db,job,5+int(50*(idx-1)/max(1,len(lidar))),f'Reusing converted LiDAR {idx}/{len(lidar)}: {f.filename}')
                reused+=1
                blocks.extend({'name':b.name,'source_object_key':f.object_key,'object_key':b.object_key,'point_count':b.point_count,
                    'x_min':b.x_min,'y_min':b.y_min,'x_max':b.x_max,'y_max':b.y_max,'zmin':b.zmin,'zmax':b.zmax} for b in previous)
                continue
            to_convert.append({'id':f.id,'filename':f.filename,'object_key':f.object_key,'size_bytes':f.size_bytes})

        def conversion_progress(done,total,running):
            current=f": {', '.join(running)}" if running else ''
            setjob(db,job,5+int(50*(reused+done)/max(1,len(lidar))),f'Converting LiDAR {done}/{total} done{current}')
        blocks.extend(convert_lidar_files(to_convert,lidar_prefix,project.crs,tmp,conversion_progress))

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
                    if source.get('source_x') is not None and source.get('source_y') is not None:
                        x,y=float(source['source_x']),float(source['source_y'])
                        candidate=next((b for b in blocks if b['x_min']<=x<=b['x_max'] and b['y_min']<=y<=b['y_max']),None)
                        if candidate:
                            block_name=candidate['name']; poles_by_block[block_name].append(source['internal_id'])
                    elif source.get('corrected_lat') is not None and source.get('corrected_lon') is not None:
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
        poles_by_block={b['name']:[] for b in blocks}; pole_xy={}; pole_block={}
        tf = Transformer.from_crs('EPSG:4326', project.crs, always_xy=True)
        for p in parsed['poles']:
            pf=pole_feature.get(p['internal_id']); block=None; x=y=None
            if pf:
                x,y=pf['geometry']['coordinates'][0][:2]
            elif p.get('source_x') is not None and p.get('source_y') is not None:
                x,y=float(p['source_x']),float(p['source_y'])
            elif p.get('corrected_lat') is not None and p.get('corrected_lon') is not None:
                x,y=tf.transform(float(p['corrected_lon']), float(p['corrected_lat']))
            if x is not None and y is not None:
                pole_xy[p['internal_id']]=(float(x),float(y))
                candidates=[b for b in blocks if b['x_min']<=x<=b['x_max'] and b['y_min']<=y<=b['y_max']]
                if candidates:
                    block=candidates[0]['name']; poles_by_block[block].append(p['internal_id'])
            pole_block[p['internal_id']]=block
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

        rules=parsed.get('rules',[])+generic_spatial_checks(db,project,parsed,blocks,pole_xy,pole_block,geojson,geo_summary)

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
            complete_qc_run(db,qc_run_id,True,{'blocks':len(blocks),'poles':len(parsed['poles']),'findings':len(parsed['findings']),'comparison':comparison,
                                              'pole_sheet':parsed.get('pole_sheet'),'rules':rule_coverage(rules,parsed['findings'])})
        project.source_workbook_key=workbook.object_key; project.status='READY_FOR_QC'
        job.status='SUCCEEDED'; job.progress=100; job.stage='Ready for QC'; job.finished_at=utcnow();
        db.add(AuditLog(actor='worker',action='PROCESS_DATASET',entity_type='project',entity_id=project.id,detail_json=json.dumps({'blocks':len(blocks),'poles':len(parsed['poles']),'findings':len(parsed['findings']),'version_id':version_id,'qc_run_id':qc_run_id,'comparison':comparison,'archived_decisions':archived_decisions})))
        db.commit()
        if qc_run_id:
            run=db.query(QCRun).filter_by(id=qc_run_id).first()
            safely(notify_qc_finished,db,project,run.created_by if run else None,True)
    except Exception as e:
        db.rollback(); job=db.query(ProcessingJob).filter_by(id=job_id).first(); project=db.query(Project).filter_by(id=job.project_id).first() if job else None
        if job:
            job.status='FAILED'; job.stage='Failed'; job.error=f'{e}\n{traceback.format_exc()}'; job.finished_at=utcnow()
        if project: project.status='FAILED'
        if qc_run_id: complete_qc_run(db,qc_run_id,False,{'error':str(e)[:1000]})
        db.commit()
        if qc_run_id and project:
            run=db.query(QCRun).filter_by(id=qc_run_id).first()
            safely(notify_qc_finished,db,project,run.created_by if run else None,False,str(e)[:500])
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
