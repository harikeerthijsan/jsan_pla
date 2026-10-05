import json, os, re, uuid, pathlib, time
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, UploadFile, File, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from .db import Base, engine, get_db, SessionLocal, initialize_schema
from .models import User,Project,DatasetFile,ProcessingJob,Pole,LidarBlock,ProductionAnnotation,ProductionGeoFeature,Finding,SceneFeature,ReviewDecision,AuditLog
from .geojson_import import geo_feature_dict, pole_locations
from .auth import current_user, verify_password, create_token, hash_password
from .rbac import ROLE_PERMISSIONS, require_permission, workspaces_for, has_permission
from .workflow import DatasetVersion, VersionFile, CorrectionRequest, QCRun, ensure_current_version, create_revision, attach_file_to_current_version, version_files, create_qc_run, create_correction, resolve_correction, approve_version, workflow_snapshot, version_dict
from .seed import seed_database, seed_admin
from .storage import MODE, LOCAL_ROOT, bucket_name, local_path, presign_put, object_exists, block_url, create_multipart, presign_upload_part, complete_multipart, read_bytes, upload_bytes, configure_bucket_cors
from .sections import vector_analysis, build_frame, section_result_key
from .production import catalogue as production_catalogue, validate_annotation_values, validate_coordinates, measurement_values, annotation_dict, project_to_wgs84, SEQUENCED_ANNOTATION_GROUPS, next_annotation_feature_type
from .workbook_editor import apply_workbook_updates, inspect_workbook, match_geojson_pole_number

APP_ENV=os.getenv('APP_ENV','development').lower()
APP_VERSION=os.getenv('APP_VERSION','3.4.1-operational')
# Staging is production-like: it gets the same startup guard so misconfiguration is caught before promotion.
STRICT_ENVIRONMENTS={'production','staging'}
DEFAULT_JWT_SECRETS={'dev-only-change-me','replace-with-a-long-random-secret','replace-with-at-least-32-random-characters'}
DEFAULT_ADMIN_PASSWORDS={'ChangeMe123!','replace-with-a-unique-password-of-12-or-more-characters'}

def validate_runtime_environment():
    """Refuse to start staging/production with unsafe configuration. Do not weaken; fix the environment."""
    if APP_ENV not in STRICT_ENVIRONMENTS: return
    errors=[]
    db_url=os.getenv('DATABASE_URL','')
    if not db_url or db_url.startswith('sqlite'): errors.append('DATABASE_URL must point to PostgreSQL, not SQLite')
    if MODE!='s3': errors.append("STORAGE_MODE must be 's3' (private object storage)")
    jwt_secret=os.getenv('JWT_SECRET','')
    if len(jwt_secret)<32 or jwt_secret in DEFAULT_JWT_SECRETS: errors.append('JWT_SECRET must be a unique value of at least 32 characters')
    admin_password=os.getenv('ADMIN_PASSWORD','')
    if len(admin_password)<12 or admin_password in DEFAULT_ADMIN_PASSWORDS: errors.append('ADMIN_PASSWORD must be a unique value of at least 12 characters')
    # The Railway image serves the UI same-origin, so an unset allowlist is valid; a wildcard never is.
    if any(x.strip()=='*' for x in os.getenv('CORS_ORIGINS','').split(',')): errors.append('CORS_ORIGINS must be an explicit allowlist, not *')
    if os.getenv('SEED_DEMO','false').lower()=='true': errors.append('SEED_DEMO must be false')
    # A Railway environment duplicated from production keeps APP_ENV=production; catch that mismatch.
    railway_env=os.getenv('RAILWAY_ENVIRONMENT_NAME','').strip().lower()
    production_name=os.getenv('PRODUCTION_RAILWAY_ENVIRONMENT','production').strip().lower()
    if railway_env:
        if APP_ENV=='production' and railway_env!=production_name: errors.append(f"APP_ENV=production but Railway environment is '{railway_env}'; set APP_ENV for this environment")
        if APP_ENV!='production' and railway_env==production_name: errors.append(f"Railway environment '{railway_env}' is production but APP_ENV={APP_ENV}")
    if errors: raise RuntimeError(f'Unsafe {APP_ENV} configuration: '+'; '.join(errors))

@asynccontextmanager
async def lifespan(app:FastAPI):
    validate_runtime_environment()
    initialize_schema(); db=SessionLocal()
    try:
        configure_bucket_cors()
        seed_admin(db)
        if os.getenv('SEED_DEMO','false').lower()=='true': seed_database(db)
    finally: db.close()
    yield

app=FastAPI(title='JSAN PLA Quality Validation API',version=APP_VERSION,lifespan=lifespan)
origins=[x.strip() for x in os.getenv('CORS_ORIGINS','http://localhost:5500,http://localhost:3000,http://127.0.0.1:5500').split(',') if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_origin_regex=os.getenv('CORS_ORIGIN_REGEX') or None,allow_credentials=True,allow_methods=['*'],allow_headers=['*'],expose_headers=['ETag'])


@app.middleware('http')
async def security_headers(request:Request,call_next):
    response=await call_next(request)
    response.headers.setdefault('X-Content-Type-Options','nosniff')
    response.headers.setdefault('X-Frame-Options','DENY')
    response.headers.setdefault('Referrer-Policy','same-origin')
    response.headers.setdefault('Permissions-Policy','camera=(), microphone=(), geolocation=()')
    if APP_ENV in STRICT_ENVIRONMENTS:
        response.headers.setdefault('Strict-Transport-Security','max-age=31536000; includeSubDomains')
    return response

class LoginIn(BaseModel): email:str; password:str
class DecisionIn(BaseModel): decision:str; comment:str|None=None
class CorrectionIn(BaseModel): comment:str|None=None
class UserCreateIn(BaseModel):
    email:str; name:str=Field(min_length=2,max_length=255); role:str='QC_REVIEWER'; password:str=Field(min_length=12,max_length=256)
class UserUpdateIn(BaseModel):
    name:str|None=None; role:str|None=None; password:str|None=Field(default=None,min_length=12,max_length=256)
class ProjectIn(BaseModel):
    name:str=Field(min_length=2,max_length=255); customer:str='PLA'; crs:str='EPSG:6424'; units:str='US survey foot'
class UploadRequest(BaseModel): filename:str; role:str; size_bytes:int|None=None; content_type:str|None=None
class MultipartComplete(BaseModel): upload_id:str; parts:list[dict]
class WorkbookReplacementIn(BaseModel): filename:str; size_bytes:int|None=None; content_type:str|None=None
class QcDatasetIn(BaseModel): include_geojson:bool=False
class SectionRequest(BaseModel):
    target_internal_id:int|None=None
    width:float=Field(default=12.0,gt=1,le=200)
    depth:float=Field(default=12.0,gt=1,le=200)
    resolution:float=Field(default=0.5,gt=0,le=50)
    max_points:int=Field(default=90000,ge=1000,le=300000)
class ProductionAnnotationIn(BaseModel):
    block_name:str=Field(min_length=1,max_length=160)
    family:str=Field(min_length=1,max_length=160)
    feature_type:str=Field(min_length=1,max_length=160)
    x:float; y:float; z:float
    pole_internal_id:int|None=None
    reference_annotation_id:str|None=Field(default=None,max_length=120)
    attributes:dict=Field(default_factory=dict)
    status:str='IN_PROGRESS'
class WorkbookCellUpdate(BaseModel):
    sheet:str=Field(min_length=1,max_length=160)
    row:int=Field(gt=1)
    column:int=Field(gt=0)
    value:Any=None
class PoleWorkbookSaveIn(BaseModel):
    snapshot_file_id:str=Field(min_length=1,max_length=120)
    updates:list[WorkbookCellUpdate]=Field(min_length=1,max_length=5000)
class CoordinateTransformIn(BaseModel):
    x:float; y:float; z:float|None=None

LOGIN_FAILURES={}
LOGIN_WINDOW_SECONDS=int(os.getenv('LOGIN_WINDOW_SECONDS','300'))
LOGIN_MAX_FAILURES=int(os.getenv('LOGIN_MAX_FAILURES','8'))
MAX_WORKBOOK_BYTES=int(os.getenv('MAX_WORKBOOK_BYTES',str(50*1024*1024)))
MAX_LIDAR_BYTES=int(os.getenv('MAX_LIDAR_BYTES',str(50*1024*1024*1024)))
MAX_GEOJSON_BYTES=int(os.getenv('MAX_GEOJSON_BYTES',str(50*1024*1024)))

def _login_key(request:Request,email:str):
    host=request.client.host if request.client else 'unknown'
    return f'{host}|{email.strip().lower()}'

def _prune_login_failures(key:str):
    cutoff=time.time()-LOGIN_WINDOW_SECONDS
    LOGIN_FAILURES[key]=[x for x in LOGIN_FAILURES.get(key,[]) if x>=cutoff]
    if not LOGIN_FAILURES[key]: LOGIN_FAILURES.pop(key,None)

def validate_upload_request(body:UploadRequest):
    safe=pathlib.Path(body.filename).name
    lower=safe.lower()
    if safe!=body.filename and ('/' in body.filename or '\\' in body.filename):
        raise HTTPException(400,'Filename must not contain a path')
    if body.size_bytes is not None and body.size_bytes<0: raise HTTPException(400,'Invalid file size')
    if body.role=='WORKBOOK':
        if not lower.endswith('.xlsx'): raise HTTPException(400,'Workbook must be .xlsx')
        if body.size_bytes is not None and body.size_bytes>MAX_WORKBOOK_BYTES: raise HTTPException(413,'Workbook exceeds configured size limit')
    elif body.role=='LIDAR_SOURCE':
        if not (lower.endswith('.las') or lower.endswith('.laz')): raise HTTPException(400,'LiDAR must be LAS/LAZ/COPC LAZ')
        if body.size_bytes is not None and body.size_bytes>MAX_LIDAR_BYTES: raise HTTPException(413,'LiDAR exceeds configured size limit')
    elif body.role=='GEOJSON':
        if not (lower.endswith('.geojson') or lower.endswith('.json')): raise HTTPException(400,'GeoJSON must be .geojson or .json')
        if body.size_bytes is not None and body.size_bytes>MAX_GEOJSON_BYTES: raise HTTPException(413,'GeoJSON exceeds configured size limit')
    else:
        raise HTTPException(400,'Unsupported file role')

def slug(s): return re.sub(r'[^a-z0-9]+','-',s.lower()).strip('-')[:50] or 'dataset'

def project_dict(p): return {'id':p.id,'name':p.name,'customer':p.customer,'status':p.status,'crs':p.crs,'units':p.units,'source_project_id':p.source_project_id,'created_at':p.created_at.isoformat() if p.created_at else None}
def is_production_dataset(db:Session,project_id:str)->bool:
    # Datasets imported in Production run LIDAR_INGEST; they are QC-checked through a linked QC dataset with its own Excel.
    return db.query(ProcessingJob.id).filter_by(project_id=project_id,job_type='LIDAR_INGEST').first() is not None
def user_dict(u): return {'id':u.id,'email':u.email,'name':u.name,'role':u.role,'created_at':u.created_at.isoformat() if u.created_at else None}
def finding_dict(f): return {'id':f.id,'rule_id':f.rule_id,'severity':f.severity,'internal_id':f.internal_id,'pole_number':f.pole_number,'sheet':f.sheet,'field':f.field,'message':f.message,'actual':f.actual,'expected':f.expected,'related_poles':json.loads(f.related_poles_json or '[]'),'status':f.status}
def pole_dict(p):
    d=json.loads(p.manifest_json or '{}'); d.update({'internal_id':p.internal_id,'pole_number':p.pole_number,'block_name':p.block_name,'source_latitude':p.corrected_lat,'source_longitude':p.corrected_lon,'verified_latitude':p.verified_lat,'verified_longitude':p.verified_lon,'verified_x':p.verified_x,'verified_y':p.verified_y,'verified_z':p.verified_z,'verified_bottom_elevation':p.verified_bottom_elevation,'verified_top_elevation':p.verified_top_elevation,'verified_height':p.verified_height,'verified_block_name':p.verified_block_name,'verified_annotation_id':p.verified_annotation_id,'verified_bottom_annotation_id':p.verified_bottom_annotation_id,'verified_top_annotation_id':p.verified_top_annotation_id,'location_verified_by':p.location_verified_by,'location_verified_at':p.location_verified_at.isoformat() if p.location_verified_at else None,'qc_status':p.qc_status,'qc_fail':p.qc_fail,'qc_review':p.qc_review,'qc_unverifiable':p.qc_unverifiable,'remarks':p.remarks,'bottom_elev_ft':p.bottom_elev_ft,'top_elev_ft':p.top_elev_ft}); return d

@app.get('/health')
def health(): return {'status':'ok','service':'pla-qc-api','version':APP_VERSION,'storage_mode':MODE}
@app.get('/health/live')
def health_live(): return {'status':'live','service':'pla-qc-api','version':APP_VERSION,'app_env':APP_ENV}
@app.get('/api/system/info')
def system_info():
    return {'version':APP_VERSION,'app_env':APP_ENV,'railway_environment':os.getenv('RAILWAY_ENVIRONMENT_NAME') or APP_ENV,'git_branch':os.getenv('RAILWAY_GIT_BRANCH') or os.getenv('GIT_BRANCH') or 'local','git_commit':(os.getenv('RAILWAY_GIT_COMMIT_SHA') or os.getenv('GIT_COMMIT') or '')[:8] or None,'service':'pla-qc'}
@app.get('/health/ready')
def health_ready():
    # Railway only switches traffic once this returns 2xx. Never echo exception text: it can contain hosts/credentials.
    checks={}
    try:
        with engine.connect() as connection: connection.execute(text('SELECT 1'))
        checks['database']='ok'
    except Exception: checks['database']='fail'
    # Configuration only, not a bucket round-trip: a transient bucket blip must not fail every deploy.
    storage_ok=bool(bucket_name()) if MODE=='s3' else (not LOCAL_ROOT.exists() or LOCAL_ROOT.is_dir())
    checks['storage']='ok' if storage_ok else 'fail'
    ready=all(v=='ok' for v in checks.values())
    body={'status':'ready' if ready else 'not_ready','service':'pla-qc-api','version':APP_VERSION,'app_env':APP_ENV,'storage_mode':MODE,'checks':checks}
    return JSONResponse(body,status_code=200 if ready else 503)
@app.post('/api/auth/login')
def login(body:LoginIn,request:Request,db:Session=Depends(get_db)):
    key=_login_key(request,body.email); _prune_login_failures(key)
    if len(LOGIN_FAILURES.get(key,[]))>=LOGIN_MAX_FAILURES: raise HTTPException(429,'Too many failed login attempts. Try again later.')
    u=db.query(User).filter(func.lower(User.email)==body.email.lower()).first()
    if not u or not verify_password(body.password,u.password_hash):
        LOGIN_FAILURES.setdefault(key,[]).append(time.time()); raise HTTPException(401,'Invalid email or password')
    LOGIN_FAILURES.pop(key,None)
    return {'token':create_token(u),'user':{'email':u.email,'name':u.name,'role':u.role}}
@app.get('/api/auth/me')
def me(u:User=Depends(current_user)): return {'email':u.email,'name':u.name,'role':u.role,'workspaces':workspaces_for(u)}
@app.get('/api/workspaces')
def workspaces(u:User=Depends(current_user)): return {'workspaces':workspaces_for(u),'permissions':sorted(ROLE_PERMISSIONS.get((u.role or '').upper(),set()))}

@app.get('/api/users')
def list_users(u:User=Depends(require_permission('user.manage')),db:Session=Depends(get_db)):
    return [user_dict(x) for x in db.query(User).order_by(User.name,User.email).all()]
@app.post('/api/users')
def create_user(body:UserCreateIn,u:User=Depends(require_permission('user.manage')),db:Session=Depends(get_db)):
    role=body.role.upper()
    if role not in ROLE_PERMISSIONS: raise HTTPException(400,'Unsupported role')
    if db.query(User).filter(func.lower(User.email)==body.email.lower()).first(): raise HTTPException(409,'User already exists')
    row=User(email=body.email.lower(),name=body.name,role=role,password_hash=hash_password(body.password)); db.add(row); db.add(AuditLog(actor=u.email,action='CREATE_USER',entity_type='user',entity_id=body.email.lower(),detail_json=json.dumps({'role':role,'name':body.name}))); db.commit(); return user_dict(row)
@app.put('/api/users/{user_id}')
def update_user(user_id:int,body:UserUpdateIn,u:User=Depends(require_permission('user.manage')),db:Session=Depends(get_db)):
    row=db.query(User).filter_by(id=user_id).first()
    if not row: raise HTTPException(404,'User not found')
    if body.name is not None: row.name=body.name
    if body.role is not None:
        role=body.role.upper()
        if role not in ROLE_PERMISSIONS: raise HTTPException(400,'Unsupported role')
        row.role=role
    if body.password is not None: row.password_hash=hash_password(body.password)
    db.add(AuditLog(actor=u.email,action='UPDATE_USER',entity_type='user',entity_id=str(row.id),detail_json=json.dumps({'role':row.role,'name':row.name,'password_changed':body.password is not None}))); db.commit(); return user_dict(row)

@app.get('/api/projects')
def projects(u:User=Depends(require_permission('project.read')),db:Session=Depends(get_db)): return [project_dict(p) for p in db.query(Project).order_by(Project.created_at.desc()).all()]
@app.post('/api/projects')
def create_project(body:ProjectIn,u:User=Depends(require_permission('project.create')),db:Session=Depends(get_db)):
    pid=f"{slug(body.name)}-{uuid.uuid4().hex[:8]}"; p=Project(id=pid,name=body.name,customer=body.customer,crs=body.crs,units=body.units,status='UPLOADING'); db.add(p); db.flush(); ensure_current_version(db,pid,u.email); db.add(AuditLog(actor=u.email,action='CREATE_PROJECT',entity_type='project',entity_id=pid,detail_json=body.model_dump_json())); db.commit(); return project_dict(p)

@app.post('/api/projects/{project_id}/uploads/prepare')
def prepare_upload(project_id:str,body:UploadRequest,u:User=Depends(require_permission('upload.create')),db:Session=Depends(get_db)):
    p=db.query(Project).filter_by(id=project_id).first()
    if not p: raise HTTPException(404,'Project not found')
    validate_upload_request(body)
    version=ensure_current_version(db,project_id,u.email)
    if version.status!='UPLOADING': raise HTTPException(409,'Create a new dataset revision before uploading new source files')
    fid=uuid.uuid4().hex; safe=pathlib.Path(body.filename).name; key=f'{project_id}/versions/v{version.version_no}/source/{fid}-{safe}'
    rec=DatasetFile(id=fid,project_id=project_id,filename=safe,role=body.role,object_key=key,content_type=body.content_type,size_bytes=body.size_bytes,status='PENDING'); db.add(rec); db.flush(); attach_file_to_current_version(db,project_id,fid,u.email); db.commit()
    return _upload_instructions(project_id,fid,key,body)

def _upload_instructions(project_id:str,fid:str,key:str,body:UploadRequest)->dict:
    if MODE=='local': return {'file_id':fid,'mode':'local','upload_url':f'/api/projects/{project_id}/uploads/{fid}/local'}
    # Large LiDAR uses multipart so browser uploads are chunked and retryable.
    threshold=int(os.getenv('MULTIPART_THRESHOLD_BYTES',str(100*1024*1024)))
    if body.size_bytes and body.size_bytes>threshold:
        part_size=int(os.getenv('MULTIPART_PART_SIZE_BYTES',str(64*1024*1024)))
        upload_id=create_multipart(key,body.content_type)
        count=(body.size_bytes+part_size-1)//part_size
        parts=[{'part_number':n,'url':presign_upload_part(key,upload_id,n)} for n in range(1,count+1)]
        return {'file_id':fid,'mode':'multipart','upload_id':upload_id,'part_size':part_size,'parts':parts}
    url=presign_put(key,body.content_type)
    return {'file_id':fid,'mode':'direct','upload_url':url,'method':'PUT','headers':({'Content-Type':body.content_type} if body.content_type else {})}

@app.put('/api/projects/{project_id}/uploads/{file_id}/local')
async def local_upload(project_id:str,file_id:str,file:UploadFile=File(...),u:User=Depends(require_permission('upload.create')),db:Session=Depends(get_db)):
    if MODE!='local': raise HTTPException(400,'Local upload endpoint disabled')
    rec=db.query(DatasetFile).filter_by(id=file_id,project_id=project_id).first()
    if not rec: raise HTTPException(404,'Upload record not found')
    dst=local_path(rec.object_key); dst.parent.mkdir(parents=True,exist_ok=True)
    size=0
    with open(dst,'wb') as fh:
        while chunk:=await file.read(8*1024*1024): fh.write(chunk); size+=len(chunk)
    rec.size_bytes=size; rec.status='UPLOADED'; db.commit(); return {'ok':True,'size_bytes':size}

@app.post('/api/projects/{project_id}/uploads/{file_id}/multipart-complete')
def multipart_complete(project_id:str,file_id:str,body:MultipartComplete,u:User=Depends(require_permission('upload.create')),db:Session=Depends(get_db)):
    rec=db.query(DatasetFile).filter_by(id=file_id,project_id=project_id).first()
    if not rec: raise HTTPException(404,'Upload record not found')
    if MODE=='local': raise HTTPException(400,'Multipart endpoint is for S3 storage mode')
    parts=[{'PartNumber':int(x['PartNumber']),'ETag':x['ETag']} for x in body.parts]
    complete_multipart(rec.object_key,body.upload_id,parts)
    rec.status='UPLOADED'; db.commit(); return {'ok':True,'file_id':file_id}

@app.post('/api/projects/{project_id}/uploads/{file_id}/complete')
def complete_upload(project_id:str,file_id:str,u:User=Depends(require_permission('upload.create')),db:Session=Depends(get_db)):
    rec=db.query(DatasetFile).filter_by(id=file_id,project_id=project_id).first()
    if not rec: raise HTTPException(404,'Upload record not found')
    if not object_exists(rec.object_key): raise HTTPException(400,'Uploaded object is not present in storage')
    rec.status='UPLOADED'; db.commit(); return {'ok':True,'file_id':file_id}

@app.get('/api/projects/{project_id}/files')
def project_files(project_id:str,u:User=Depends(current_user),db:Session=Depends(get_db)):
    if not db.query(Project).filter_by(id=project_id).first(): raise HTTPException(404,'Project not found')
    return [{'id':f.id,'filename':f.filename,'role':f.role,'size_bytes':f.size_bytes,'status':f.status} for f in db.query(DatasetFile).filter_by(project_id=project_id).order_by(DatasetFile.created_at).all()]

@app.get('/api/projects/{project_id}/lidar-blocks')
def project_lidar_blocks(project_id:str,u:User=Depends(require_permission('project.read')),db:Session=Depends(get_db)):
    if not db.query(Project).filter_by(id=project_id).first(): raise HTTPException(404,'Project not found')
    files={f.object_key:f.filename for f in db.query(DatasetFile).filter_by(project_id=project_id,role='LIDAR_SOURCE').all()}
    return [{'id':b.id,'name':b.name,'source_filename':files.get(b.source_object_key),'point_count':b.point_count,
             'bounds':{'x_min':b.x_min,'y_min':b.y_min,'z_min':b.zmin,'x_max':b.x_max,'y_max':b.y_max,'z_max':b.zmax},
             'copc_url':block_url(b.object_key)}
            for b in db.query(LidarBlock).filter_by(project_id=project_id).order_by(LidarBlock.name).all()]

@app.get('/api/production/catalogue')
def get_production_catalogue(u:User=Depends(require_permission('project.read'))):
    return production_catalogue()

@app.post('/api/projects/{project_id}/coordinates/to-wgs84')
def coordinates_to_wgs84(project_id:str,body:CoordinateTransformIn,u:User=Depends(require_permission('project.read')),db:Session=Depends(get_db)):
    project=db.query(Project).filter_by(id=project_id).first()
    if not project: raise HTTPException(404,'Project not found')
    validate_coordinates(body.x,body.y,body.z or 0.0)
    latitude,longitude=project_to_wgs84(project.crs,body.x,body.y)
    return {'project_crs':project.crs,'x':body.x,'y':body.y,'z':body.z,'latitude':latitude,'longitude':longitude}

@app.get('/api/projects/{project_id}/production-geo-features')
def list_production_geo_features(project_id:str,u:User=Depends(require_permission('project.read')),db:Session=Depends(get_db)):
    project=db.query(Project).filter_by(id=project_id).first()
    if not project: raise HTTPException(404,'Project not found')
    rows=db.query(ProductionGeoFeature).filter_by(project_id=project_id).order_by(ProductionGeoFeature.feature_index).all()
    poles=db.query(Pole).filter_by(project_id=project_id).all() if any(row.pole_internal_id is not None for row in rows) else []
    locations={location['internal_id']:location for location in pole_locations(project,poles)}
    return [geo_feature_dict(row,locations.get(row.pole_internal_id)) for row in rows]

def _pole_workbook_context(project_id:str,internal_id:int,db:Session):
    project=db.query(Project).filter_by(id=project_id).first()
    if not project: raise HTTPException(404,'Project not found')
    pole=db.query(Pole).filter_by(project_id=project_id,internal_id=internal_id).first()
    if not pole: raise HTTPException(404,'Pole not found')
    version=db.query(DatasetVersion).filter_by(project_id=project_id).order_by(DatasetVersion.version_no.desc()).first()
    if not version: raise HTTPException(404,'Dataset version not found')
    ordered_files=(db.query(DatasetFile)
        .join(VersionFile,VersionFile.file_id==DatasetFile.id)
        .filter(VersionFile.version_id==version.id,DatasetFile.status=='UPLOADED')
        .order_by(VersionFile.id).all())
    files=ordered_files
    edited=[file for file in files if file.role=='WORKBOOK_EDITED']
    sources=[file for file in files if file.role=='WORKBOOK']
    workbook_file=(edited or sources)[-1] if edited or sources else None
    if not workbook_file: raise HTTPException(404,'No workbook is uploaded for the active dataset version')
    geojson_ids=[file.id for file in files if file.role=='GEOJSON']
    geo_rows=(db.query(ProductionGeoFeature).filter(ProductionGeoFeature.project_id==project_id,ProductionGeoFeature.source_file_id.in_(geojson_ids)).order_by(ProductionGeoFeature.feature_index).all() if geojson_ids else [])
    geo_features=[{'geometry_type':row.geometry_type,'properties':json.loads(row.properties_json or '{}')} for row in geo_rows]
    geojson_match=match_geojson_pole_number(geo_features,pole.pole_number)
    try:
        contents=read_bytes(workbook_file.object_key)
    except FileNotFoundError as exc:
        raise HTTPException(404,'Workbook object is not available in storage') from exc
    return project,pole,version,workbook_file,contents,geojson_match

@app.get('/api/projects/{project_id}/poles/{internal_id}/workbook')
def get_pole_workbook(project_id:str,internal_id:int,u:User=Depends(require_permission('project.read')),db:Session=Depends(get_db)):
    project,pole,version,workbook_file,contents,geojson_match=_pole_workbook_context(project_id,internal_id,db)
    try:
        result=inspect_workbook(contents,pole.pole_number)
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from exc
    result.update({
        'project_id':project_id,
        'version_id':version.id,
        'snapshot_file_id':workbook_file.id,
        'geojson_match':geojson_match,
        'download_available':workbook_file.role=='WORKBOOK_EDITED',
        'editable':geojson_match['status']=='MATCHED' and version.status not in {'APPROVED','ARCHIVED'} and has_permission(u,'production.annotate'),
    })
    return result

@app.put('/api/projects/{project_id}/poles/{internal_id}/workbook')
def save_pole_workbook(project_id:str,internal_id:int,body:PoleWorkbookSaveIn,u:User=Depends(require_permission('production.annotate')),db:Session=Depends(get_db)):
    locked_version=(db.query(DatasetVersion).filter_by(project_id=project_id)
        .order_by(DatasetVersion.version_no.desc()).with_for_update().first())
    if not locked_version: raise HTTPException(404,'Dataset version not found')
    project,pole,version,workbook_file,contents,geojson_match=_pole_workbook_context(project_id,internal_id,db)
    if version.id!=locked_version.id: raise HTTPException(409,'The active dataset version changed. Reload the workbook before saving.')
    if version.status in {'APPROVED','ARCHIVED'}: raise HTTPException(409,'Create a new dataset revision before editing its workbook')
    if body.snapshot_file_id!=workbook_file.id: raise HTTPException(409,'The workbook changed since it was loaded. Reload it before saving.')
    if geojson_match['status']!='MATCHED': raise HTTPException(422,'Workbook editing requires one exact GeoJSON Pole Number match')
    updates=[cell.model_dump() for cell in body.updates]
    try:
        updated=apply_workbook_updates(contents,pole.pole_number,updates)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    if len(updated)>MAX_WORKBOOK_BYTES: raise HTTPException(413,'Updated workbook exceeds configured size limit')

    source_files=[file for file in version_files(db,version.id) if file.role=='WORKBOOK']
    source_name=pathlib.Path(source_files[-1].filename if source_files else workbook_file.filename).name
    stem=pathlib.Path(source_name).stem or 'workbook'
    filename=f'{stem}-updated.xlsx'
    file_id=uuid.uuid4().hex
    key=f'{project_id}/versions/v{version.version_no}/derived/workbooks/{file_id}-{filename}'
    upload_bytes(updated,key,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    latest_version=db.query(DatasetVersion).filter_by(project_id=project_id).order_by(DatasetVersion.version_no.desc()).first()
    if not latest_version or latest_version.id!=version.id: raise HTTPException(409,'The active dataset version changed. Reload the workbook before saving.')
    new_file=DatasetFile(id=file_id,project_id=project_id,filename=filename,role='WORKBOOK_EDITED',object_key=key,
                         content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',size_bytes=len(updated),status='UPLOADED')
    db.add(new_file); db.flush(); db.add(VersionFile(version_id=version.id,file_id=file_id))
    original=inspect_workbook(contents,pole.pole_number)
    column_names={(sheet['name'],column):header for sheet in original['worksheets'] for column,header in zip(sheet['columns'],sheet['headers'])}
    changed_columns=sorted({f"{update['sheet']}:{column_names.get((update['sheet'],update['column']),update['column'])}" for update in updates})
    db.add(AuditLog(actor=u.email,action='UPDATE_PRODUCTION_WORKBOOK',entity_type='pole_workbook',
                    entity_id=f'{project_id}:{version.id}:{internal_id}',detail_json=json.dumps({
                        'project_id':project_id,'version_id':version.id,'pole_internal_id':internal_id,
                        'snapshot_file_id':workbook_file.id,'updated_file_id':file_id,
                        'updates':len(updates),'worksheet_columns':changed_columns,
                    })))
    db.commit()
    try:
        result=inspect_workbook(updated,pole.pole_number)
    except ValueError as exc:
        raise HTTPException(500,'Saved workbook could not be reopened') from exc
    result.update({'project_id':project_id,'version_id':version.id,'snapshot_file_id':file_id,
                   'geojson_match':geojson_match,'download_available':True,'editable':True})
    return result

@app.get('/api/projects/{project_id}/poles/{internal_id}/workbook-download')
def download_pole_workbook(project_id:str,internal_id:int,u:User=Depends(require_permission('project.read')),db:Session=Depends(get_db)):
    _,_,version,workbook_file,contents,_=_pole_workbook_context(project_id,internal_id,db)
    files=(db.query(DatasetFile)
        .join(VersionFile,VersionFile.file_id==DatasetFile.id)
        .filter(VersionFile.version_id==version.id)
        .order_by(VersionFile.id).all())
    edited=[file for file in files if file.role=='WORKBOOK_EDITED' and file.status=='UPLOADED']
    if not edited or edited[-1].id!=workbook_file.id: raise HTTPException(404,'Save workbook changes before downloading the updated Excel file')
    filename=re.sub(r'[^A-Za-z0-9._-]+','_',pathlib.Path(workbook_file.filename).name)
    return Response(content=contents,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition':f'attachment; filename="{filename}"'})

@app.get('/api/projects/{project_id}/production-annotations')
def list_production_annotations(project_id:str,u:User=Depends(require_permission('project.read')),db:Session=Depends(get_db)):
    if not db.query(Project).filter_by(id=project_id).first(): raise HTTPException(404,'Project not found')
    rows=db.query(ProductionAnnotation).filter_by(project_id=project_id).order_by(ProductionAnnotation.created_at,ProductionAnnotation.id).all()
    return [annotation_dict(row) for row in rows]

@app.get('/api/projects/{project_id}/production-annotations.geojson')
def download_production_annotations_geojson(project_id:str,u:User=Depends(require_permission('project.read')),db:Session=Depends(get_db)):
    project=db.query(Project).filter_by(id=project_id).first()
    if not project: raise HTTPException(404,'Project not found')
    rows=db.query(ProductionAnnotation).filter_by(project_id=project_id).order_by(ProductionAnnotation.created_at,ProductionAnnotation.id).all()
    pole_numbers={pole.internal_id:pole.pole_number for pole in db.query(Pole).filter_by(project_id=project_id).all()}
    features=[]
    for row in rows:
        latitude,longitude=row.latitude,row.longitude
        if latitude is None or longitude is None:
            latitude,longitude=project_to_wgs84(project.crs,row.x,row.y)
        details=annotation_dict(row)
        properties={
            'annotation_id':row.id,
            'pole_number':pole_numbers.get(row.pole_internal_id),
            'pole_internal_id':row.pole_internal_id,
            'point_name':row.feature_type,
            'annotation_group':row.family,
            'block_name':row.block_name,
            'project_crs':project.crs,
            'x':row.x,'y':row.y,'z':row.z,
            'verified_latitude':latitude,'verified_longitude':longitude,
            'status':row.status,
            'reference_annotation_id':row.reference_annotation_id,
            **details['measurements'],
            **details['attributes'],
            'created_by':row.created_by,'modified_by':row.modified_by,
            'created_at':details['created_at'],'updated_at':details['updated_at'],
        }
        features.append({'type':'Feature','id':row.id,'geometry':{'type':'Point','coordinates':[longitude,latitude,row.z]},'properties':properties})
    document={
        'type':'FeatureCollection',
        'name':f'{project.name} production annotation points',
        'project_id':project.id,
        'source_crs':project.crs,
        'feature_count':len(features),
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'features':features,
    }
    basename=re.sub(r'[^A-Za-z0-9._-]+','_',project.name).strip('._') or 'production'
    filename=f'{basename}-annotation-points.geojson'
    return Response(content=json.dumps(document,ensure_ascii=False,separators=(',',':')),media_type='application/geo+json',headers={'Content-Disposition':f'attachment; filename="{filename}"'})

def _apply_production_annotation(row:ProductionAnnotation,body:ProductionAnnotationIn,actor:str,db:Session):
    validate_annotation_values(body.family,body.feature_type,body.status,body.attributes)
    validate_coordinates(body.x,body.y,body.z)
    project=db.query(Project).filter_by(id=row.project_id).first()
    if not project: raise HTTPException(404,'Project not found')
    if not db.query(LidarBlock).filter_by(project_id=row.project_id,name=body.block_name).first(): raise HTTPException(422,'LiDAR block does not belong to this project')
    pole=None
    if body.pole_internal_id is not None:
        pole=db.query(Pole).filter_by(project_id=row.project_id,internal_id=body.pole_internal_id).first()
        if not pole: raise HTTPException(422,'Selected pole does not belong to this project workbook')
    vertical,horizontal,distance=measurement_values(db,row.project_id,body.x,body.y,body.z,body.reference_annotation_id)
    latitude,longitude=project_to_wgs84(project.crs,body.x,body.y)
    row.block_name=body.block_name; row.family=body.family; row.feature_type=body.feature_type
    row.x=body.x; row.y=body.y; row.z=body.z; row.latitude=latitude; row.longitude=longitude; row.pole_internal_id=body.pole_internal_id; row.reference_annotation_id=body.reference_annotation_id
    row.vertical_delta=vertical; row.horizontal_offset=horizontal; row.distance_3d=distance
    row.attributes_json=json.dumps(body.attributes,default=str); row.status=body.status
    is_pole_base=(body.family=='Pole Points' and body.feature_type=='Pole Base / Ground Point') or (body.family=='poles' and body.feature_type=='Pole_Base')
    is_pole_top=(body.family=='Pole Points' and body.feature_type=='Pole Top Point') or (body.family=='poles' and body.feature_type=='Pole_Top')
    if pole and is_pole_base:
        pole.verified_lat=latitude; pole.verified_lon=longitude
        pole.verified_x=body.x; pole.verified_y=body.y; pole.verified_z=body.z
        pole.verified_bottom_elevation=body.z; pole.verified_bottom_annotation_id=row.id
        pole.verified_block_name=body.block_name; pole.verified_annotation_id=row.id
        pole.location_verified_by=actor; pole.location_verified_at=datetime.now(timezone.utc)
    elif pole and is_pole_top:
        pole.verified_top_elevation=body.z; pole.verified_top_annotation_id=row.id
        pole.location_verified_by=actor; pole.location_verified_at=datetime.now(timezone.utc)
    if pole and (is_pole_base or is_pole_top):
        pole.verified_height=pole.verified_top_elevation-pole.verified_bottom_elevation if pole.verified_top_elevation is not None and pole.verified_bottom_elevation is not None else None
        action='VERIFY_POLE_LOCATION' if is_pole_base else 'VERIFY_POLE_ELEVATION'
        db.add(AuditLog(actor=actor,action=action,entity_type='pole',entity_id=f'{row.project_id}:{pole.internal_id}',detail_json=json.dumps({'annotation_id':row.id,'feature_type':body.feature_type,'block_name':body.block_name,'project_crs':project.crs,'x':body.x,'y':body.y,'z':body.z,'latitude':latitude,'longitude':longitude,'verified_height':pole.verified_height})))

def _clear_pole_verification_for_annotation(db:Session,project_id:str,annotation_id:str,pole_internal_id:int|None=None):
    query=db.query(Pole).filter_by(project_id=project_id)
    if pole_internal_id is not None: query=query.filter(Pole.internal_id==pole_internal_id)
    for pole in query.all():
        changed=False
        if pole.verified_annotation_id==annotation_id or pole.verified_bottom_annotation_id==annotation_id:
            pole.verified_lat=pole.verified_lon=pole.verified_x=pole.verified_y=pole.verified_z=None
            pole.verified_bottom_elevation=None; pole.verified_bottom_annotation_id=None
            pole.verified_block_name=pole.verified_annotation_id=None
            changed=True
        if pole.verified_top_annotation_id==annotation_id:
            pole.verified_top_elevation=None; pole.verified_top_annotation_id=None
            changed=True
        if changed:
            pole.verified_height=pole.verified_top_elevation-pole.verified_bottom_elevation if pole.verified_top_elevation is not None and pole.verified_bottom_elevation is not None else None
            pole.location_verified_by=pole.location_verified_at=None

@app.post('/api/projects/{project_id}/production-annotations')
def create_production_annotation(project_id:str,body:ProductionAnnotationIn,u:User=Depends(require_permission('production.annotate')),db:Session=Depends(get_db)):
    if not db.query(Project).filter_by(id=project_id).first(): raise HTTPException(404,'Project not found')
    if body.family in SEQUENCED_ANNOTATION_GROUPS:
        if body.pole_internal_id is None: raise HTTPException(422,'Select a Pole Number before saving this annotation group')
        pole_lock=db.query(Pole).filter_by(project_id=project_id,internal_id=body.pole_internal_id).with_for_update().first()
        if not pole_lock: raise HTTPException(422,'Selected pole does not belong to this project workbook')
        body=body.model_copy(update={'feature_type':next_annotation_feature_type(db,project_id,body.pole_internal_id,body.family)})
    row=ProductionAnnotation(id=uuid.uuid4().hex,project_id=project_id,block_name=body.block_name,family=body.family,feature_type=body.feature_type,x=body.x,y=body.y,z=body.z,created_by=u.email,modified_by=u.email)
    _apply_production_annotation(row,body,u.email,db); db.add(row); db.flush()
    db.add(AuditLog(actor=u.email,action='CREATE_PRODUCTION_ANNOTATION',entity_type='production_annotation',entity_id=row.id,detail_json=json.dumps({'project_id':project_id,'block_name':row.block_name,'feature_type':row.feature_type})))
    db.commit(); db.refresh(row); return annotation_dict(row)

@app.put('/api/projects/{project_id}/production-annotations/{annotation_id}')
def update_production_annotation(project_id:str,annotation_id:str,body:ProductionAnnotationIn,u:User=Depends(require_permission('production.annotate')),db:Session=Depends(get_db)):
    row=db.query(ProductionAnnotation).filter_by(id=annotation_id,project_id=project_id).first()
    if not row: raise HTTPException(404,'Production annotation not found')
    if body.reference_annotation_id==row.id: raise HTTPException(422,'An annotation cannot reference itself')
    if body.family in SEQUENCED_ANNOTATION_GROUPS:
        if body.pole_internal_id is None: raise HTTPException(422,'Select a Pole Number before saving this annotation group')
        pole_lock=db.query(Pole).filter_by(project_id=project_id,internal_id=body.pole_internal_id).with_for_update().first()
        if not pole_lock: raise HTTPException(422,'Selected pole does not belong to this project workbook')
        feature_type=(row.feature_type if row.family==body.family and row.pole_internal_id==body.pole_internal_id
                      else next_annotation_feature_type(db,project_id,body.pole_internal_id,body.family,exclude_annotation_id=row.id))
        body=body.model_copy(update={'feature_type':feature_type})
    before=annotation_dict(row); previous_pole_id=row.pole_internal_id
    _clear_pole_verification_for_annotation(db,project_id,row.id,previous_pole_id)
    _apply_production_annotation(row,body,u.email,db); row.modified_by=u.email
    db.add(AuditLog(actor=u.email,action='UPDATE_PRODUCTION_ANNOTATION',entity_type='production_annotation',entity_id=row.id,detail_json=json.dumps({'before':before,'feature_type':row.feature_type},default=str)))
    db.commit(); db.refresh(row); return annotation_dict(row)

@app.delete('/api/projects/{project_id}/production-annotations/{annotation_id}')
def delete_production_annotation(project_id:str,annotation_id:str,u:User=Depends(require_permission('production.annotate')),db:Session=Depends(get_db)):
    row=db.query(ProductionAnnotation).filter_by(id=annotation_id,project_id=project_id).first()
    if not row: raise HTTPException(404,'Production annotation not found')
    if db.query(ProductionAnnotation).filter_by(project_id=project_id,reference_annotation_id=row.id).first(): raise HTTPException(409,'Remove dependent measurement references before deleting this annotation')
    snapshot=annotation_dict(row); _clear_pole_verification_for_annotation(db,project_id,row.id); db.delete(row)
    db.add(AuditLog(actor=u.email,action='DELETE_PRODUCTION_ANNOTATION',entity_type='production_annotation',entity_id=row.id,detail_json=json.dumps(snapshot,default=str)))
    db.commit(); return {'ok':True,'id':annotation_id}

@app.post('/api/projects/{project_id}/process-lidar')
def queue_lidar_process(project_id:str,u:User=Depends(require_permission('processing.run')),db:Session=Depends(get_db)):
    p=db.query(Project).filter_by(id=project_id).first()
    if not p: raise HTTPException(404,'Project not found')
    version=ensure_current_version(db,project_id,u.email)
    files=[f for f in version_files(db,version.id) if f.status=='UPLOADED']
    if not any(f.role=='LIDAR_SOURCE' for f in files): raise HTTPException(400,'Upload at least one LAS/LAZ/COPC file first')
    jid=uuid.uuid4().hex
    job=ProcessingJob(id=jid,project_id=project_id,job_type='LIDAR_INGEST',payload_json=json.dumps({'version_id':version.id}),status='QUEUED',progress=0,stage='Queued LiDAR conversion')
    db.add(job); p.status='PROCESSING'
    db.add(AuditLog(actor=u.email,action='QUEUE_LIDAR_PROCESSING',entity_type='project',entity_id=project_id,detail_json=json.dumps({'job_id':jid,'version_id':version.id})))
    db.commit()
    return {'job_id':jid,'status':'QUEUED','version_id':version.id}

@app.post('/api/projects/{project_id}/process')
def queue_process(project_id:str,u:User=Depends(require_permission('processing.run')),db:Session=Depends(get_db)):
    p=db.query(Project).filter_by(id=project_id).first()
    if not p: raise HTTPException(404,'Project not found')
    if is_production_dataset(db,project_id): raise HTTPException(409,'Production datasets are QC-checked in a linked QC dataset with its own Excel. Use "Run QC now" in the QC tab.')
    version=ensure_current_version(db,project_id,u.email); files=[f for f in version_files(db,version.id) if f.status=='UPLOADED']
    if not any(f.role=='WORKBOOK' for f in files): raise HTTPException(400,'Upload a COLLECTION workbook for this version first')
    if not any(f.role=='LIDAR_SOURCE' for f in files): raise HTTPException(400,'Upload or inherit at least one LAS/LAZ/COPC file for this version first')
    jid=uuid.uuid4().hex; j=ProcessingJob(id=jid,project_id=project_id,job_type='INGEST',payload_json='{}',status='QUEUED',progress=0,stage='Queued'); db.add(j); db.flush(); version,run=create_qc_run(db,project_id,jid,u.email); j.payload_json=json.dumps({'version_id':version.id,'qc_run_id':run.id}); p.status='PROCESSING'; db.add(AuditLog(actor=u.email,action='QUEUE_PROCESSING',entity_type='project',entity_id=project_id,detail_json=json.dumps({'job_id':jid,'version_id':version.id,'qc_run_id':run.id}))); db.commit(); return {'job_id':jid,'status':'QUEUED','version_id':version.id,'qc_run_id':run.id}
def _active_processing(db:Session,project_id:str)->bool:
    return db.query(ProcessingJob.id).filter(ProcessingJob.project_id==project_id,ProcessingJob.job_type.in_(['LIDAR_INGEST','INGEST']),ProcessingJob.status.in_(['QUEUED','RUNNING'])).first() is not None

@app.post('/api/projects/{project_id}/production-workbook/prepare')
def prepare_workbook_replacement(project_id:str,body:WorkbookReplacementIn,u:User=Depends(require_permission('upload.create')),db:Session=Depends(get_db)):
    if not db.query(Project).filter_by(id=project_id).first(): raise HTTPException(404,'Project not found')
    if not is_production_dataset(db,project_id): raise HTTPException(409,'Excel replacement is available for Production datasets')
    request=UploadRequest(filename=body.filename,role='WORKBOOK',size_bytes=body.size_bytes,content_type=body.content_type); validate_upload_request(request)
    version=ensure_current_version(db,project_id,u.email)
    if version.status in {'APPROVED','ARCHIVED'}: raise HTTPException(409,'Create a new dataset revision before replacing its Excel')
    fid=uuid.uuid4().hex; safe=pathlib.Path(body.filename).name; key=f'{project_id}/versions/v{version.version_no}/source/{fid}-{safe}'
    # Not attached to the version until applied, so an abandoned upload never replaces the current Excel.
    db.add(DatasetFile(id=fid,project_id=project_id,filename=safe,role='WORKBOOK',object_key=key,content_type=body.content_type,size_bytes=body.size_bytes,status='PENDING')); db.commit()
    return _upload_instructions(project_id,fid,key,request)

@app.post('/api/projects/{project_id}/production-workbook/{file_id}/apply')
def apply_workbook_replacement(project_id:str,file_id:str,u:User=Depends(require_permission('upload.create')),db:Session=Depends(get_db)):
    if not has_permission(u,'processing.run'): raise HTTPException(403,f'Role {u.role} is not authorized for processing.run')
    p=db.query(Project).filter_by(id=project_id).first()
    if not p: raise HTTPException(404,'Project not found')
    if not is_production_dataset(db,project_id): raise HTTPException(409,'Excel replacement is available for Production datasets')
    rec=db.query(DatasetFile).filter_by(id=file_id,project_id=project_id,role='WORKBOOK').first()
    if not rec: raise HTTPException(404,'Replacement Excel not found')
    if rec.status!='UPLOADED' and not object_exists(rec.object_key): raise HTTPException(400,'The new Excel has not finished uploading')
    if _active_processing(db,project_id): raise HTTPException(409,'Processing is already running for this dataset; try again when it finishes')
    rec.status='UPLOADED'
    version=ensure_current_version(db,project_id,u.email)
    replaced=[]
    for f in version_files(db,version.id):
        # The wrong Excel and any edits made to it are retired, never deleted.
        if f.id!=rec.id and f.role in {'WORKBOOK','WORKBOOK_EDITED'} and f.status=='UPLOADED': f.status='SUPERSEDED'; replaced.append(f.filename)
    attach_file_to_current_version(db,project_id,rec.id,u.email)
    jid=uuid.uuid4().hex
    db.add(ProcessingJob(id=jid,project_id=project_id,job_type='LIDAR_INGEST',payload_json=json.dumps({'version_id':version.id,'replaced_workbook':True}),status='QUEUED',progress=0,stage='Queued Excel replacement'))
    p.status='PROCESSING'
    db.add(AuditLog(actor=u.email,action='REPLACE_PRODUCTION_WORKBOOK',entity_type='project',entity_id=project_id,detail_json=json.dumps({'file_id':rec.id,'filename':rec.filename,'replaced':replaced,'job_id':jid,'version_id':version.id})))
    db.commit()
    return {'job_id':jid,'status':'QUEUED','replaced':replaced}

@app.post('/api/projects/{project_id}/qc-dataset')
def create_qc_dataset(project_id:str,body:QcDatasetIn,u:User=Depends(require_permission('processing.run')),db:Session=Depends(get_db)):
    source=db.query(Project).filter_by(id=project_id).first()
    if not source: raise HTTPException(404,'Project not found')
    if not is_production_dataset(db,project_id): raise HTTPException(409,'QC datasets are created from Production datasets')
    existing=db.query(Project).filter_by(source_project_id=project_id).order_by(Project.created_at.desc()).first()
    if existing: return {**project_dict(existing),'existing':True}
    blocks=db.query(LidarBlock).filter_by(project_id=project_id).all()
    if not blocks: raise HTTPException(409,'The Production LiDAR is not ready yet')
    source_files=[f for f in version_files(db,ensure_current_version(db,project_id,u.email).id) if f.status=='UPLOADED']
    qc_id=f"{slug(source.name)}-qc-{uuid.uuid4().hex[:8]}"
    qc=Project(id=qc_id,name=f'{source.name} · QC',customer=source.customer,crs=source.crs,units=source.units,status='UPLOADING',source_project_id=project_id)
    db.add(qc); db.flush(); ensure_current_version(db,qc_id,u.email)
    # Share the Production LiDAR by reference (same objects, no copy or reconversion). The Production Excel is never linked.
    shared={'lidar':0,'geojson':0}
    for f in source_files:
        if f.role=='LIDAR_SOURCE' or (body.include_geojson and f.role=='GEOJSON'):
            fid=uuid.uuid4().hex
            db.add(DatasetFile(id=fid,project_id=qc_id,filename=f.filename,role=f.role,object_key=f.object_key,content_type=f.content_type,size_bytes=f.size_bytes,status='UPLOADED')); db.flush()
            attach_file_to_current_version(db,qc_id,fid,u.email); shared['lidar' if f.role=='LIDAR_SOURCE' else 'geojson']+=1
    for b in blocks:
        db.add(LidarBlock(project_id=qc_id,name=b.name,source_object_key=b.source_object_key,object_key=b.object_key,point_count=b.point_count,x_min=b.x_min,y_min=b.y_min,x_max=b.x_max,y_max=b.y_max,zmin=b.zmin,zmax=b.zmax,poles_json='[]'))
    db.add(AuditLog(actor=u.email,action='CREATE_QC_DATASET',entity_type='project',entity_id=qc_id,detail_json=json.dumps({'source_project_id':project_id,**shared})))
    db.commit()
    return {**project_dict(qc),'existing':False,'shared':shared}

@app.get('/api/jobs/{job_id}')
def get_job(job_id:str,u:User=Depends(current_user),db:Session=Depends(get_db)):
    j=db.query(ProcessingJob).filter_by(id=job_id).first()
    if not j: raise HTTPException(404,'Job not found')
    return {'id':j.id,'project_id':j.project_id,'job_type':j.job_type,'status':j.status,'progress':j.progress,'stage':j.stage,'message':j.message,'error':j.error,'result_key':j.result_key}

@app.get('/api/projects/{project_id}/summary')
def summary(project_id:str,u:User=Depends(current_user),db:Session=Depends(get_db)):
    poles=db.query(Pole).filter_by(project_id=project_id).all(); fs=db.query(Finding).filter_by(project_id=project_id).all(); p=db.query(Project).filter_by(id=project_id).first()
    if not p: raise HTTPException(404,'Project not found')
    # Lets the QC tab offer QC on LiDAR already imported in Production, without another upload.
    version=db.query(DatasetVersion).filter_by(project_id=project_id).order_by(DatasetVersion.version_no.desc()).first()
    version_roles={f.role for f in version_files(db,version.id) if f.status=='UPLOADED'} if version else set()
    runs=db.query(QCRun).filter_by(project_id=project_id).all()
    active_run=next((r for r in runs if r.status in {'QUEUED','RUNNING'}),None)
    qc_dataset=db.query(Project).filter_by(source_project_id=project_id).order_by(Project.created_at.desc()).first()
    source=db.query(Project).filter_by(id=p.source_project_id).first() if p.source_project_id else None
    production={'lidar_blocks':db.query(LidarBlock).filter_by(project_id=project_id).count(),'has_workbook':'WORKBOOK' in version_roles,
                'has_geojson':'GEOJSON' in version_roles,'qc_runs':len(runs),'qc_job_id':active_run.processing_job_id if active_run else None,
                'production_dataset':is_production_dataset(db,project_id),
                'qc_dataset':{'id':qc_dataset.id,'name':qc_dataset.name} if qc_dataset else None,
                'source_project':{'id':source.id,'name':source.name} if source else None}
    return {**production,'project_id':project_id,'project_status':p.status,'poles':len(poles),'poles_pass':sum(x.qc_status=='PASS' for x in poles),'poles_fail':sum(x.qc_status=='FAIL' for x in poles),'poles_review':sum(x.qc_status=='REVIEW' for x in poles),'poles_unverifiable':sum(x.qc_status=='UNVERIFIABLE' for x in poles),'findings':len(fs),'fail':sum(x.severity=='FAIL' for x in fs),'review':sum(x.severity=='REVIEW' for x in fs),'unverifiable':sum(x.severity=='UNVERIFIABLE' for x in fs),'open_findings':sum(x.status=='OPEN' for x in fs)}
@app.get('/api/projects/{project_id}/poles')
def poles(project_id:str,u:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.query(Pole).filter_by(project_id=project_id).order_by(Pole.internal_id).all()
    project=db.query(Project).filter_by(id=project_id).first()
    # Workbook lat/lon expressed in the project CRS so the viewer can navigate to poles not yet verified in LiDAR.
    try: locations={location['internal_id']:location for location in pole_locations(project,rows)} if project and rows else {}
    except Exception: locations={}
    return [{**pole_dict(p),'workbook_x':locations.get(p.internal_id,{}).get('workbook_x'),'workbook_y':locations.get(p.internal_id,{}).get('workbook_y')} for p in rows]
@app.get('/api/projects/{project_id}/findings')
def findings(project_id:str,severity:str|None=None,internal_id:int|None=None,status:str|None=None,u:User=Depends(current_user),db:Session=Depends(get_db)):
    q=db.query(Finding).filter_by(project_id=project_id)
    if severity:q=q.filter(Finding.severity==severity)
    if internal_id:q=q.filter(Finding.internal_id==internal_id)
    if status:q=q.filter(Finding.status==status)
    return [finding_dict(f) for f in q.order_by(Finding.internal_id,Finding.id).all()]
@app.get('/api/projects/{project_id}/poles/{internal_id}/scene')
def scene(project_id:str,internal_id:int,include_related:bool=Query(True),u:User=Depends(current_user),db:Session=Depends(get_db)):
    p=db.query(Pole).filter_by(project_id=project_id,internal_id=internal_id).first()
    if not p: raise HTTPException(404,'Pole not found')
    fs=db.query(Finding).filter_by(project_id=project_id,internal_id=internal_id).all(); related=sorted(set(x for f in fs for x in json.loads(f.related_poles_json or '[]'))); ids=[internal_id]+(related if include_related else [])
    feats=db.query(SceneFeature).filter(SceneFeature.project_id==project_id,SceneFeature.internal_id.in_(ids)).all(); selected=db.query(Pole).filter(Pole.project_id==project_id,Pole.internal_id.in_(ids)).all(); names=sorted(set(x.block_name for x in selected if x.block_name)); blocks=[]
    for b in db.query(LidarBlock).filter(LidarBlock.project_id==project_id,LidarBlock.name.in_(names)).all(): blocks.append({'name':b.name,'bbox':[b.x_min,b.y_min,b.x_max,b.y_max],'copc_url':block_url(b.object_key),'object_key':b.object_key,'point_count':b.point_count})
    return {'project_id':project_id,'pole':pole_dict(p),'related_poles':related,'block':next((b for b in blocks if b['name']==p.block_name),None),'blocks':blocks,'features':[json.loads(x.payload_json) for x in feats],'findings':[finding_dict(f) for f in fs]}

@app.get('/api/projects/{project_id}/poles/{internal_id}/analysis-frame')
def analysis_frame(project_id:str,internal_id:int,target_internal_id:int|None=None,u:User=Depends(current_user),db:Session=Depends(get_db)):
    try: return vector_analysis(db,project_id,internal_id,target_internal_id)
    except ValueError as e: raise HTTPException(422,str(e))

@app.post('/api/projects/{project_id}/poles/{internal_id}/sections/prepare')
def prepare_section(project_id:str,internal_id:int,body:SectionRequest,u:User=Depends(require_permission('analysis.run')),db:Session=Depends(get_db)):
    p=db.query(Pole).filter_by(project_id=project_id,internal_id=internal_id).first()
    if not p: raise HTTPException(404,'Pole not found')
    try: frame=build_frame(db,project_id,internal_id,body.target_internal_id)
    except ValueError as e: raise HTTPException(422,str(e))
    target=frame.get('target_internal_id')
    current_version=db.query(DatasetVersion).filter_by(project_id=project_id).order_by(DatasetVersion.version_no.desc()).first()
    key=section_result_key(project_id,internal_id,target,body.width,body.depth,body.resolution,body.max_points,current_version.id if current_version else None)
    if object_exists(key):
        return {'cached':True,'result_key':key,'frame':frame}
    payload={'internal_id':internal_id,'target_internal_id':target,'width':body.width,'depth':body.depth,'resolution':body.resolution,'max_points':body.max_points}
    jid=uuid.uuid4().hex
    job=ProcessingJob(id=jid,project_id=project_id,job_type='SECTION',payload_json=json.dumps(payload),status='QUEUED',progress=0,stage='Queued profile / section extraction')
    db.add(job); db.add(AuditLog(actor=u.email,action='QUEUE_SECTION',entity_type='pole',entity_id=f'{project_id}:{internal_id}',detail_json=json.dumps(payload))); db.commit()
    return {'cached':False,'job_id':jid,'frame':frame}

@app.get('/api/jobs/{job_id}/result')
def job_result(job_id:str,u:User=Depends(current_user),db:Session=Depends(get_db)):
    j=db.query(ProcessingJob).filter_by(id=job_id).first()
    if not j: raise HTTPException(404,'Job not found')
    if j.status!='SUCCEEDED' or not j.result_key: raise HTTPException(409,'Job result is not ready')
    try: return json.loads(read_bytes(j.result_key))
    except Exception as e: raise HTTPException(500,f'Unable to read job result: {e}')

@app.get('/api/projects/{project_id}/analysis/result')
def analysis_result(project_id:str,key:str,u:User=Depends(current_user)):
    # Small JSON analysis products may be returned through the API; large COPC files remain direct-from-storage.
    allowed_prefixes=(f'{project_id}/analysis/',f'{project_id}/versions/')
    if not key.startswith(allowed_prefixes) or '/analysis/' not in key or not key.endswith('.json'): raise HTTPException(400,'Invalid analysis key')
    try: return json.loads(read_bytes(key))
    except FileNotFoundError: raise HTTPException(404,'Analysis result not found')
    except Exception as e: raise HTTPException(500,f'Unable to read analysis result: {e}')

@app.post('/api/findings/{finding_id}/decision')
def decide(finding_id:str,body:DecisionIn,u:User=Depends(require_permission('finding.review')),db:Session=Depends(get_db)):
    allowed={'CONFIRMED_FAIL','ACCEPTED_EXCEPTION','NEEDS_FIELD_REVIEW','CORRECTED','OPEN'}
    if body.decision not in allowed: raise HTTPException(400,'Unsupported decision')
    f=db.query(Finding).filter_by(id=finding_id).first()
    if not f: raise HTTPException(404,'Finding not found')
    f.status=body.decision; db.add(ReviewDecision(finding_id=f.id,reviewer_email=u.email,decision=body.decision,comment=body.comment)); db.add(AuditLog(actor=u.email,action='FINDING_DECISION',entity_type='finding',entity_id=f.id,detail_json=json.dumps({'decision':body.decision,'comment':body.comment}))); db.commit(); return {'ok':True,'finding':finding_dict(f)}
@app.get('/api/findings/{finding_id}/history')
def history(finding_id:str,u:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.query(ReviewDecision).filter_by(finding_id=finding_id).order_by(ReviewDecision.created_at.desc()).all(); return [{'reviewer':r.reviewer_email,'decision':r.decision,'comment':r.comment,'created_at':r.created_at.isoformat()} for r in rows]


@app.get('/api/projects/{project_id}/workflow')
def project_workflow(project_id:str,u:User=Depends(require_permission('project.read')),db:Session=Depends(get_db)):
    if not db.query(Project).filter_by(id=project_id).first(): raise HTTPException(404,'Project not found')
    snap=workflow_snapshot(db,project_id,u.email); db.commit(); return snap

@app.post('/api/projects/{project_id}/versions')
def new_version(project_id:str,u:User=Depends(require_permission('version.create')),db:Session=Depends(get_db)):
    v=create_revision(db,project_id,u.email); db.commit(); return version_dict(v)

@app.get('/api/projects/{project_id}/corrections')
def project_corrections(project_id:str,u:User=Depends(require_permission('project.read')),db:Session=Depends(get_db)):
    snap=workflow_snapshot(db,project_id,u.email); db.commit(); return snap['corrections']

@app.post('/api/findings/{finding_id}/correction')
def request_correction(finding_id:str,body:CorrectionIn,u:User=Depends(require_permission('correction.create')),db:Session=Depends(get_db)):
    f=db.query(Finding).filter_by(id=finding_id).first()
    if not f: raise HTTPException(404,'Finding not found')
    row=create_correction(db,f,u.email,body.comment); db.commit(); return {'id':row.id,'status':row.status,'finding_id':row.finding_id}

@app.post('/api/corrections/{correction_id}/resolve')
def close_correction(correction_id:str,u:User=Depends(require_permission('correction.resolve')),db:Session=Depends(get_db)):
    row=resolve_correction(db,correction_id,u.email); db.commit(); return {'id':row.id,'status':row.status}

@app.post('/api/projects/{project_id}/versions/{version_id}/approve')
def approve_dataset(project_id:str,version_id:str,u:User=Depends(require_permission('version.approve')),db:Session=Depends(get_db)):
    row=approve_version(db,project_id,version_id,u.email); db.commit(); return version_dict(row)

@app.get('/api/storage/{key:path}')
def local_storage(key:str):
    if MODE!='local': raise HTTPException(404,'Not available')
    p=local_path(key)
    if not p.exists(): raise HTTPException(404,'Object not found')
    return FileResponse(p)


# The Railway image serves the static workbench and API from one public domain.
# Mounting last preserves every API route plus FastAPI's /docs and /openapi.json.
web_root=pathlib.Path(os.getenv('WEB_ROOT',pathlib.Path(__file__).resolve().parents[2]/'web'))
if web_root.is_dir():
    app.mount('/',StaticFiles(directory=web_root,html=True),name='web')
