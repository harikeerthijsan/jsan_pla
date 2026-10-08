import json, logging, os, re, uuid, pathlib, time, tempfile
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, UploadFile, File, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, text
from .db import Base, engine, get_db, SessionLocal, initialize_schema
from .models import iso_utc,User,Project,DatasetFile,ProcessingJob,Pole,LidarBlock,ProductionAnnotation,ProductionGeoFeature,Finding,SceneFeature,ReviewDecision,AuditLog,PoleAssignment,PolePresence,Notification
from .geojson_import import geo_feature_dict, pole_locations
from .auth import current_user, verify_password, create_token, hash_password
from .rbac import ROLE_PERMISSIONS, require_permission, workspaces_for, has_permission, normalize_role, is_admin_role, is_super_admin
from .workflow import DatasetVersion, VersionFile, CorrectionRequest, FindingRevision, FindingComparison, ReviewDecisionArchive, ProcessingLease, QCRun, ensure_current_version, create_revision, attach_file_to_current_version, version_files, create_qc_run, create_correction, resolve_correction, approve_version, workflow_snapshot, version_dict
from .seed import promote_super_admins, seed_database, seed_admin, seed_staff_accounts
from .ingest import parse_workbook
from .pipeline import pipeline as pipeline_snapshot, production_project_ids
from .team import router as team_router, hidden_authors
from .super_admin import router as super_admin_router
from .notifications import router as notifications_router, safely, notify_correction_requested, notify_correction_resolved, notify_version_approved
from .deliverables import build_package, ensure_package
from .network_access import client_ip, get_network_policy, ip_on_listed_network, set_network_policy, user_network_allowed
from .storage import MODE, LOCAL_ROOT, bucket_name, local_path, presign_put, object_exists, list_objects, delete_objects, block_url, create_multipart, presign_upload_part, complete_multipart, read_bytes, upload_bytes, configure_bucket_cors
from .sections import vector_analysis, build_frame, section_result_key
from .production import annotations_feature_collection, parent_attributes, resolve_parent, catalogue as production_catalogue, validate_annotation_values, validate_coordinates, measurement_values, annotation_dict, project_to_wgs84, SEQUENCED_ANNOTATION_GROUPS, next_annotation_feature_type
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
    staff_password=os.getenv('STAFF_INITIAL_PASSWORD','')
    if staff_password and (len(staff_password)<12 or staff_password in DEFAULT_ADMIN_PASSWORDS): errors.append('STAFF_INITIAL_PASSWORD must be a unique value of at least 12 characters')
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
        seed_staff_accounts(db)
        promote_super_admins(db)
        if os.getenv('SEED_DEMO','false').lower()=='true': seed_database(db)
    finally: db.close()
    yield

app=FastAPI(title='JSAN PLA Quality Validation API',version=APP_VERSION,lifespan=lifespan)
app.include_router(team_router)
app.include_router(notifications_router)
app.include_router(super_admin_router)
origins=[x.strip() for x in os.getenv('CORS_ORIGINS','http://localhost:5500,http://localhost:3000,http://127.0.0.1:5500').split(',') if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_origin_regex=os.getenv('CORS_ORIGIN_REGEX') or None,allow_credentials=True,allow_methods=['*'],allow_headers=['*'],expose_headers=['ETag'])


@app.middleware('http')
async def security_headers(request:Request,call_next):
    response=await call_next(request)
    response.headers.setdefault('X-Content-Type-Options','nosniff')
    response.headers.setdefault('X-Frame-Options','DENY')
    response.headers.setdefault('Referrer-Policy','same-origin')
    # The app's own pages may ask for location (sign-in area); embedded third-party content may not.
    response.headers.setdefault('Permissions-Policy','camera=(), microphone=(), geolocation=(self)')
    if APP_ENV in STRICT_ENVIRONMENTS:
        response.headers.setdefault('Strict-Transport-Security','max-age=31536000; includeSubDomains')
    return response

class LoginIn(BaseModel): email:str; password:str
class DecisionIn(BaseModel): decision:str; comment:str|None=None
class CorrectionIn(BaseModel): comment:str|None=None
class UserCreateIn(BaseModel):
    email:str; name:str=Field(min_length=2,max_length=255); role:str='QC_REVIEWER'; password:str=Field(min_length=12,max_length=256)
    username:str|None=Field(default=None,max_length=80,pattern=r'^[A-Za-z0-9._-]*$'); remote_access:bool|None=None
class UserUpdateIn(BaseModel):
    name:str|None=None; role:str|None=None; password:str|None=Field(default=None,min_length=12,max_length=256); active:bool|None=None; remote_access:bool|None=None
class NetworkEntryIn(BaseModel):
    cidr:str=Field(min_length=2,max_length=64); label:str=Field(default='',max_length=80)
class NetworkPolicyIn(BaseModel):
    enabled:bool; networks:list[NetworkEntryIn]=Field(default_factory=list,max_length=50)
class PasswordChangeIn(BaseModel):
    current_password:str=Field(min_length=1,max_length=256); new_password:str=Field(min_length=12,max_length=256)
class ProfileIn(BaseModel): name:str=Field(min_length=2,max_length=255)
class SignInLocationIn(BaseModel):
    status:str=Field(pattern='^(shared|denied|unavailable)$')
    latitude:float|None=Field(default=None,ge=-90,le=90); longitude:float|None=Field(default=None,ge=-180,le=180)
    accuracy:float|None=Field(default=None,ge=0,le=1_000_000)
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
    # The revision the editor loaded; a mismatch means someone else saved this point since.
    expected_revision:int|None=Field(default=None,ge=1)
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
def user_dict(u): return {'id':u.id,'email':u.email,'username':u.username,'name':u.name,'role':u.role,'must_change_password':bool(u.must_change_password),'active':bool(u.is_active),'remote_access':bool(u.remote_access),**sign_in_dict(u),'created_at':u.created_at.isoformat() if u.created_at else None}
def sign_in_dict(u):
    shared=u.last_login_location_status=='shared' and u.last_login_latitude is not None
    return {'last_login_at':iso_utc(u.last_login_at),'last_login_ip':u.last_login_ip,
            'last_login_location':{'status':u.last_login_location_status,'latitude':u.last_login_latitude if shared else None,'longitude':u.last_login_longitude if shared else None,
                                   'accuracy':u.last_login_accuracy if shared else None,'at':iso_utc(u.last_login_location_at)}}
def account_dict(u): return {'id':u.id,'email':u.email,'username':u.username,'name':u.name,'role':u.role,'must_change_password':bool(u.must_change_password),**sign_in_dict(u)}
def finding_dict(f): return {'id':f.id,'rule_id':f.rule_id,'severity':f.severity,'internal_id':f.internal_id,'pole_number':f.pole_number,'sheet':f.sheet,'field':f.field,'message':f.message,'actual':f.actual,'expected':f.expected,'related_poles':json.loads(f.related_poles_json or '[]'),'status':f.status}
def pole_dict(p):
    d=json.loads(p.manifest_json or '{}'); d.update({'internal_id':p.internal_id,'pole_number':p.pole_number,'block_name':p.block_name,'source_latitude':p.corrected_lat,'source_longitude':p.corrected_lon,'verified_latitude':p.verified_lat,'verified_longitude':p.verified_lon,'verified_x':p.verified_x,'verified_y':p.verified_y,'verified_z':p.verified_z,'verified_bottom_elevation':p.verified_bottom_elevation,'verified_top_elevation':p.verified_top_elevation,'verified_height':p.verified_height,'verified_block_name':p.verified_block_name,'verified_annotation_id':p.verified_annotation_id,'verified_bottom_annotation_id':p.verified_bottom_annotation_id,'verified_top_annotation_id':p.verified_top_annotation_id,'location_verified_by':p.location_verified_by,'location_verified_at':p.location_verified_at.isoformat() if p.location_verified_at else None,'qc_status':p.qc_status,'qc_fail':p.qc_fail,'qc_review':p.qc_review,'qc_unverifiable':p.qc_unverifiable,'remarks':p.remarks,'bottom_elev_ft':p.bottom_elev_ft,'top_elev_ft':p.top_elev_ft}); return d

def visible_annotations(db:Session,u:User,project_id:str):
    query=db.query(ProductionAnnotation).filter_by(project_id=project_id)
    hidden=hidden_authors(db,u)
    return query.filter(ProductionAnnotation.created_by.notin_(hidden)) if hidden else query
def hidden_annotation_ids(db:Session,u:User,project_id:str)->set[str]:
    hidden=hidden_authors(db,u)
    if not hidden: return set()
    return {row_id for (row_id,) in db.query(ProductionAnnotation.id).filter(ProductionAnnotation.project_id==project_id,ProductionAnnotation.created_by.in_(hidden)).all()}
def visible_annotation(db:Session,u:User,project_id:str,annotation_id:str):
    row=visible_annotations(db,u,project_id).filter(ProductionAnnotation.id==annotation_id).first()
    if not row: raise HTTPException(404,'Production annotation not found')
    return row
def visible_pole_dict(p,hidden_ids:set[str]):
    d=pole_dict(p)
    if not hidden_ids: return d
    if p.verified_bottom_annotation_id in hidden_ids or p.verified_annotation_id in hidden_ids:
        for key in ('verified_latitude','verified_longitude','verified_x','verified_y','verified_z','verified_bottom_elevation','verified_block_name','verified_annotation_id','verified_bottom_annotation_id'): d[key]=None
    if p.verified_top_annotation_id in hidden_ids:
        d['verified_top_elevation']=None; d['verified_top_annotation_id']=None
    if d['verified_bottom_elevation'] is None or d['verified_top_elevation'] is None: d['verified_height']=None
    if d['verified_latitude'] is None and d['verified_top_elevation'] is None: d['location_verified_by']=d['location_verified_at']=None
    return d

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
    # The sign-in field accepts a username (JSAN001, Admin001) or an email address.
    login_name=body.email.strip().lower()
    u=db.query(User).filter(or_(func.lower(User.email)==login_name,func.lower(User.username)==login_name)).first()
    if not u or not verify_password(body.password,u.password_hash):
        LOGIN_FAILURES.setdefault(key,[]).append(time.time()); raise HTTPException(401,'Invalid username or password')
    LOGIN_FAILURES.pop(key,None)
    if not u.is_active: raise HTTPException(403,'This account is deactivated. Ask an admin to reactivate it.')
    ip=client_ip(request)
    if not user_network_allowed(db,u,ip):
        db.add(AuditLog(actor=u.email,action='LOGIN_BLOCKED_NETWORK',entity_type='user',entity_id=str(u.id),detail_json=json.dumps({'ip':ip}))); db.commit()
        raise HTTPException(403,'This account can only be used from the office network. Ask an admin to allow access from anywhere.')
    # Only the latest sign-in is kept. The browser reports its location separately, if the person allows it.
    u.last_login_at=datetime.now(timezone.utc); u.last_login_ip=ip; u.last_login_location_status='pending'
    u.last_login_latitude=u.last_login_longitude=u.last_login_accuracy=None; u.last_login_location_at=None
    db.commit()
    return {'token':create_token(u),'user':account_dict(u)}
@app.get('/api/auth/me')
def me(u:User=Depends(current_user)): return {**account_dict(u),'workspaces':workspaces_for(u)}
@app.post('/api/auth/change-password')
def change_password(body:PasswordChangeIn,u:User=Depends(current_user),db:Session=Depends(get_db)):
    if not verify_password(body.current_password,u.password_hash): raise HTTPException(400,'Current password is incorrect')
    if body.new_password==body.current_password: raise HTTPException(400,'Choose a new password that differs from the current one')
    # Ends every other sign-in; this device gets a fresh token and stays signed in.
    u.password_hash=hash_password(body.new_password); u.must_change_password=False; u.token_version=(u.token_version or 0)+1
    db.add(AuditLog(actor=u.email,action='CHANGE_OWN_PASSWORD',entity_type='user',entity_id=str(u.id),detail_json='{}')); db.commit()
    return {'ok':True,'user':account_dict(u),'token':create_token(u)}
SIGN_IN_LOCATION_WINDOW=timedelta(minutes=15)
@app.post('/api/auth/sign-in-location')
def sign_in_location(body:SignInLocationIn,u:User=Depends(current_user),db:Session=Depends(get_db)):
    # Accepted only right after a sign-in, so it always describes where that sign-in happened.
    signed_in=u.last_login_at.replace(tzinfo=timezone.utc) if u.last_login_at and u.last_login_at.tzinfo is None else u.last_login_at
    if not signed_in or datetime.now(timezone.utc)-signed_in>SIGN_IN_LOCATION_WINDOW: raise HTTPException(409,'Location can only be recorded right after signing in')
    if body.status=='shared' and (body.latitude is None or body.longitude is None): raise HTTPException(422,'Latitude and longitude are required when the location is shared')
    u.last_login_location_status=body.status; u.last_login_location_at=datetime.now(timezone.utc)
    if body.status=='shared': u.last_login_latitude,u.last_login_longitude,u.last_login_accuracy=body.latitude,body.longitude,body.accuracy
    else: u.last_login_latitude=u.last_login_longitude=u.last_login_accuracy=None
    db.commit(); return sign_in_dict(u)
@app.put('/api/auth/profile')
def update_profile(body:ProfileIn,u:User=Depends(current_user),db:Session=Depends(get_db)):
    before=u.name; u.name=body.name.strip()
    db.add(AuditLog(actor=u.email,action='UPDATE_OWN_PROFILE',entity_type='user',entity_id=str(u.id),detail_json=json.dumps({'name_before':before,'name':u.name}))); db.commit()
    return account_dict(u)
@app.get('/api/workspaces')
def workspaces(u:User=Depends(current_user)): return {'workspaces':workspaces_for(u),'permissions':sorted(ROLE_PERMISSIONS.get((u.role or '').upper(),set()))}

def visible_accounts(db:Session,u:User):
    """Accounts this manager may see: super admins are invisible to everyone except other super admins."""
    rows=db.query(User).order_by(User.name,User.email)
    return rows.all() if is_super_admin(u) else rows.filter(func.upper(User.role)!='SUPER_ADMIN').all()

def require_account_authority(u:User,*roles:str|None):
    """Admin and super-admin accounts (and granting those roles) are managed only by super admins."""
    if any(is_admin_role(role) for role in roles) and not has_permission(u,'user.manage_admins'):
        raise HTTPException(403,'Only a super admin can manage admin accounts')

def active_super_admins(db:Session,exclude_id:int|None=None)->int:
    q=db.query(User.id).filter(func.upper(User.role)=='SUPER_ADMIN',User.is_active.is_(True))
    return (q.filter(User.id!=exclude_id) if exclude_id is not None else q).count()

@app.get('/api/users')
def list_users(u:User=Depends(require_permission('user.manage')),db:Session=Depends(get_db)):
    return [user_dict(x) for x in visible_accounts(db,u)]
@app.post('/api/users')
def create_user(body:UserCreateIn,u:User=Depends(require_permission('user.manage')),db:Session=Depends(get_db)):
    role=body.role.upper()
    if role not in ROLE_PERMISSIONS: raise HTTPException(400,'Unsupported role')
    require_account_authority(u,role)
    if db.query(User).filter(func.lower(User.email)==body.email.lower()).first(): raise HTTPException(409,'User already exists')
    username=(body.username or '').strip() or None
    if username and db.query(User.id).filter(func.lower(User.username)==username.lower()).first(): raise HTTPException(409,'Username already exists')
    # New admins work from anywhere unless a super admin limits them; users start office-only (as before).
    remote=body.remote_access if body.remote_access is not None else role in {'ADMIN','SUPER_ADMIN'}
    row=User(email=body.email.lower(),username=username,name=body.name,role=role,password_hash=hash_password(body.password),must_change_password=True,remote_access=remote); db.add(row); db.add(AuditLog(actor=u.email,action='CREATE_USER',entity_type='user',entity_id=body.email.lower(),detail_json=json.dumps({'role':role,'name':body.name}))); db.commit(); return user_dict(row)
@app.put('/api/users/{user_id}')
def update_user(user_id:int,body:UserUpdateIn,u:User=Depends(require_permission('user.manage')),db:Session=Depends(get_db)):
    row=db.query(User).filter_by(id=user_id).first()
    if not row or (normalize_role(row.role)=='SUPER_ADMIN' and not is_super_admin(u)): raise HTTPException(404,'User not found')
    role=body.role.upper() if body.role is not None else row.role
    if role not in ROLE_PERMISSIONS: raise HTTPException(400,'Unsupported role')
    if body.active is False and row.id==u.id: raise HTTPException(409,'You cannot deactivate your own account')
    require_account_authority(u,row.role,role)
    active=row.is_active if body.active is None else body.active
    if row.id==u.id and normalize_role(row.role)=='SUPER_ADMIN' and normalize_role(role)!='SUPER_ADMIN':
        raise HTTPException(409,'You cannot remove your own super admin role')
    # Keep at least one active super admin once the role exists, so admins can always be managed.
    if normalize_role(row.role)=='SUPER_ADMIN' and row.is_active and not (normalize_role(role)=='SUPER_ADMIN' and active) and not active_super_admins(db,row.id):
        raise HTTPException(409,'At least one active super admin account is required')
    # Keep at least one active admin so the application can always be administered.
    if (is_admin_role(row.role) and row.is_active) and not (is_admin_role(role) and active):
        other_admins=db.query(User.id).filter(func.upper(User.role).in_(['ADMIN','SUPER_ADMIN']),User.is_active.is_(True),User.id!=row.id).count()
        if not other_admins: raise HTTPException(409,'At least one active admin account is required')
    if body.name is not None: row.name=body.name
    if normalize_role(role)!=normalize_role(row.role):
        db.add(AuditLog(actor=u.email,action='CHANGE_ROLE',entity_type='user',entity_id=str(row.id),detail_json=json.dumps({'username':row.username,'email':row.email,'from':row.role,'to':role})))
    row.role=role
    # An admin-set password is temporary: the person replaces it at their next sign-in. Resetting a
    # password or deactivating an account ends that account's existing sign-ins.
    if body.password is not None:
        row.password_hash=hash_password(body.password); row.must_change_password=row.id!=u.id; row.token_version=(row.token_version or 0)+1
    if body.remote_access is not None and body.remote_access!=bool(row.remote_access):
        row.remote_access=body.remote_access
        db.add(AuditLog(actor=u.email,action='ALLOW_REMOTE_ACCESS' if body.remote_access else 'REVOKE_REMOTE_ACCESS',entity_type='user',entity_id=str(row.id),detail_json=json.dumps({'username':row.username,'email':row.email})))
    if body.active is not None and body.active!=row.is_active:
        row.is_active=body.active
        if not body.active: row.token_version=(row.token_version or 0)+1
        db.add(AuditLog(actor=u.email,action='REACTIVATE_USER' if body.active else 'DEACTIVATE_USER',entity_type='user',entity_id=str(row.id),detail_json=json.dumps({'username':row.username,'email':row.email})))
    db.add(AuditLog(actor=u.email,action='UPDATE_USER',entity_type='user',entity_id=str(row.id),detail_json=json.dumps({'role':row.role,'name':row.name,'active':row.is_active,'password_changed':body.password is not None}))); db.commit(); return user_dict(row)

def _network_policy_view(db:Session,request:Request,u:User)->dict:
    policy=get_network_policy(db); ip=client_ip(request)
    return {**policy,'your_ip':ip,'your_ip_listed':ip_on_listed_network(ip,policy['networks']),
            'users_with_remote_access':db.query(User.id).filter(User.remote_access.is_(True),func.upper(User.role)=='USER').count(),
            'admins_with_remote_access':db.query(User.id).filter(User.remote_access.is_(True),func.upper(User.role)=='ADMIN').count() if is_super_admin(u) else None}
@app.get('/api/admin/network-access')
def network_access_policy(request:Request,u:User=Depends(require_permission('user.manage')),db:Session=Depends(get_db)):
    return _network_policy_view(db,request,u)
@app.put('/api/admin/network-access')
def update_network_access_policy(body:NetworkPolicyIn,request:Request,u:User=Depends(require_permission('user.manage')),db:Session=Depends(get_db)):
    before=get_network_policy(db)
    try: saved=set_network_policy(db,body.enabled,[entry.model_dump() for entry in body.networks],u.email)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    db.add(AuditLog(actor=u.email,action='UPDATE_NETWORK_POLICY',entity_type='settings',entity_id='user_network_policy',detail_json=json.dumps({'before':{k:before[k] for k in ('enabled','networks')},'after':saved,'ip':client_ip(request)})))
    db.commit(); return _network_policy_view(db,request,u)

@app.get('/api/projects')
def projects(u:User=Depends(require_permission('project.read')),db:Session=Depends(get_db)):
    production_ids=production_project_ids(db)
    return [{**project_dict(p),'production_dataset':p.id in production_ids} for p in db.query(Project).order_by(Project.created_at.desc()).all()]

def project_deletion_blocker(db:Session,project_id:str)->str|None:
    """Why this project cannot be deleted right now, or None when deletion is allowed."""
    if db.query(ProcessingJob.id).filter(ProcessingJob.project_id==project_id,ProcessingJob.status.in_(['QUEUED','RUNNING'])).first():
        return 'Wait for project processing to finish before deleting this import'
    protected=db.query(DatasetVersion.version_no).filter(DatasetVersion.project_id==project_id,DatasetVersion.status.in_(['APPROVED','ARCHIVED'])).order_by(DatasetVersion.version_no).first()
    if protected: return f'This project has an approved or archived version v{protected[0]} and cannot be deleted'
    linked=db.query(Project.name).filter(Project.source_project_id==project_id).first()
    if linked: return f'Its LiDAR is shared with the QC dataset "{linked[0]}". Delete that QC dataset first'
    return None

def project_owned_keys(db:Session,project:Project)->list[str]:
    """Storage objects this project owns: everything under its own key prefix. Objects it merely references from
    another project (a QC dataset borrows its Production dataset's LiDAR) are never part of its deletion."""
    prefix=f'{project.id}/'
    files=db.query(DatasetFile.object_key).filter_by(project_id=project.id).all()
    blocks=db.query(LidarBlock.object_key,LidarBlock.source_object_key).filter_by(project_id=project.id).all()
    jobs=db.query(ProcessingJob.result_key).filter_by(project_id=project.id).all()
    referenced=[project.source_workbook_key,*[k for (k,) in files],*[k for row in blocks for k in row],*[k for (k,) in jobs]]
    return list(dict.fromkeys([*list_objects(prefix),*[key for key in referenced if key and key.startswith(prefix)]]))

@app.get('/api/admin/imports')
def admin_imports(u:User=Depends(require_permission('project.delete')),db:Session=Depends(get_db)):
    projects=db.query(Project).order_by(Project.created_at.desc()).all()
    files_by_project={project.id:[] for project in projects}
    if files_by_project:
        for file in db.query(DatasetFile).filter(DatasetFile.project_id.in_(files_by_project)).order_by(DatasetFile.created_at).all():
            files_by_project[file.project_id].append({'id':file.id,'filename':file.filename,'role':file.role,'size_bytes':file.size_bytes,'status':file.status,'created_at':iso_utc(file.created_at),
                                                      'shared':not (file.object_key or '').startswith(f'{file.project_id}/')})
    names={project.id:project.name for project in projects}
    out=[]
    for project in projects:
        blocker=project_deletion_blocker(db,project.id)
        out.append({'id':project.id,'name':project.name,'customer':project.customer,'status':project.status,'created_at':iso_utc(project.created_at),
                    'source_project':{'id':project.source_project_id,'name':names.get(project.source_project_id)} if project.source_project_id else None,
                    'can_delete':blocker is None,'blocked_reason':blocker,'files':files_by_project[project.id]})
    return out

@app.delete('/api/projects/{project_id}')
def delete_project_import(project_id:str,u:User=Depends(require_permission('project.delete')),db:Session=Depends(get_db)):
    project=db.query(Project).filter_by(id=project_id).first()
    if not project: raise HTTPException(404,'Project not found')
    blocker=project_deletion_blocker(db,project_id)
    if blocker: raise HTTPException(409,blocker)
    try: object_keys=project_owned_keys(db,project)
    except Exception as exc:
        logging.getLogger(__name__).exception('Project storage listing failed for %s',project_id)
        raise HTTPException(502,'Project storage could not be listed; no project data was changed.') from exc
    # Never delete an object another dataset still uses.
    if object_keys:
        others=or_(
            db.query(DatasetFile.id).filter(DatasetFile.object_key.in_(object_keys),DatasetFile.project_id!=project_id).exists(),
            db.query(LidarBlock.id).filter(LidarBlock.project_id!=project_id,or_(LidarBlock.object_key.in_(object_keys),LidarBlock.source_object_key.in_(object_keys))).exists(),
            db.query(ProcessingJob.id).filter(ProcessingJob.project_id!=project_id,ProcessingJob.result_key.in_(object_keys)).exists(),
            db.query(Project.id).filter(Project.id!=project_id,Project.source_workbook_key.in_(object_keys)).exists())
        if db.query(others).scalar():
            raise HTTPException(409,'This project contains storage objects used by another dataset and cannot be deleted')

    files=db.query(DatasetFile).filter_by(project_id=project_id).all()
    blocks=db.query(LidarBlock).filter_by(project_id=project_id).all()
    version_ids=[row[0] for row in db.query(DatasetVersion.id).filter_by(project_id=project_id).all()]
    job_ids=[row[0] for row in db.query(ProcessingJob.id).filter_by(project_id=project_id).all()]
    finding_ids=[row[0] for row in db.query(Finding.id).filter_by(project_id=project_id).all()]
    run_ids=[row[0] for row in db.query(QCRun.id).filter(QCRun.project_id==project_id).all()]
    file_ids=[file.id for file in files]; name=project.name; deleted_files=len(files); deleted_blocks=len(blocks)
    # Stage every row deletion first (children before parents), then delete storage, then commit: if storage
    # deletion fails the transaction is rolled back and nothing changes, and a retry finds the same objects
    # (objects already removed count as deleted).
    if finding_ids: db.query(ReviewDecision).filter(ReviewDecision.finding_id.in_(finding_ids)).delete(synchronize_session=False)
    if version_ids or run_ids: db.query(FindingRevision).filter(or_(FindingRevision.version_id.in_(version_ids),FindingRevision.qc_run_id.in_(run_ids))).delete(synchronize_session=False)
    db.query(CorrectionRequest).filter(CorrectionRequest.project_id==project_id).delete(synchronize_session=False)
    db.query(ReviewDecisionArchive).filter(ReviewDecisionArchive.project_id==project_id).delete(synchronize_session=False)
    db.query(FindingComparison).filter(FindingComparison.project_id==project_id).delete(synchronize_session=False)
    db.query(QCRun).filter(QCRun.project_id==project_id).delete(synchronize_session=False)
    if job_ids: db.query(ProcessingLease).filter(ProcessingLease.job_id.in_(job_ids)).delete(synchronize_session=False)
    if version_ids or file_ids: db.query(VersionFile).filter(or_(VersionFile.version_id.in_(version_ids),VersionFile.file_id.in_(file_ids))).delete(synchronize_session=False)
    for model in (ProductionAnnotation,ProductionGeoFeature,SceneFeature,PoleAssignment,PolePresence,Notification,Finding,Pole,LidarBlock,ProcessingJob,DatasetFile):
        db.query(model).filter_by(project_id=project_id).delete(synchronize_session=False)
    if version_ids: db.query(DatasetVersion).filter(DatasetVersion.id.in_(version_ids)).delete(synchronize_session=False)
    db.delete(project)
    db.add(AuditLog(actor=u.email,action='DELETE_PROJECT',entity_type='project',entity_id=project_id,
        detail_json=json.dumps({'project_id':project_id,'name':name,'source_project_id':project.source_project_id,'file_count':deleted_files,
                                'block_count':deleted_blocks,'object_count':len(object_keys),'object_keys':object_keys[:200]})))
    try:
        db.flush()  # surfaces any constraint problem before a single object is deleted
        delete_objects(object_keys)
    except Exception as exc:
        db.rollback()
        logging.getLogger(__name__).exception('Project deletion failed for %s; database changes rolled back',project_id)
        raise HTTPException(502,'The project could not be deleted; nothing was changed in the database. Retry the deletion.') from exc
    db.commit()
    return {'ok':True,'project_id':project_id,'name':name,'deleted_files':deleted_files,'deleted_blocks':deleted_blocks,'deleted_objects':len(object_keys)}

@app.get('/api/projects/{project_id}/pipeline')
def project_pipeline(project_id:str,u:User=Depends(require_permission('project.read')),db:Session=Depends(get_db)):
    project=db.query(Project).filter_by(id=project_id).first()
    if not project: raise HTTPException(404,'Project not found')
    return pipeline_snapshot(db,project)
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
def project_lidar_blocks(project_id:str,request:Request,u:User=Depends(require_permission('project.read')),db:Session=Depends(get_db)):
    if not db.query(Project).filter_by(id=project_id).first(): raise HTTPException(404,'Project not found')
    files={f.object_key:f.filename for f in db.query(DatasetFile).filter_by(project_id=project_id,role='LIDAR_SOURCE').all()}
    return [{'id':b.id,'name':b.name,'source_filename':files.get(b.source_object_key),'point_count':b.point_count,
             'bounds':{'x_min':b.x_min,'y_min':b.y_min,'z_min':b.zmin,'x_max':b.x_max,'y_max':b.y_max,'z_max':b.zmax},
             'copc_url':block_url(b.object_key,str(request.base_url))}
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
    geojson_match=match_geojson_pole_number(geo_features,pole.pole_number,pole.internal_id)
    try:
        contents=read_bytes(workbook_file.object_key)
    except FileNotFoundError as exc:
        raise HTTPException(404,'Workbook object is not available in storage') from exc
    return project,pole,version,workbook_file,contents,geojson_match

@app.get('/api/projects/{project_id}/poles/{internal_id}/workbook')
def get_pole_workbook(project_id:str,internal_id:int,u:User=Depends(require_permission('project.read')),db:Session=Depends(get_db)):
    project,pole,version,workbook_file,contents,geojson_match=_pole_workbook_context(project_id,internal_id,db)
    try:
        result=inspect_workbook(contents,pole.pole_number,pole.internal_id)
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from exc
    result.update({
        'project_id':project_id,
        'version_id':version.id,
        'snapshot_file_id':workbook_file.id,
        'geojson_match':geojson_match,
        'download_available':workbook_file.role=='WORKBOOK_EDITED',
        'editable':geojson_match['status']=='MATCHED' and version.status not in {'APPROVED','ARCHIVED'} and has_permission(u,'production.annotate'),
        'internal_id_editable':has_permission(u,'workbook.edit_internal_id'),
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
        updated=apply_workbook_updates(contents,pole.pole_number,updates,internal_id=pole.internal_id,allow_internal_id=has_permission(u,'workbook.edit_internal_id'))
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
    original=inspect_workbook(contents,pole.pole_number,pole.internal_id)
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
        result=inspect_workbook(updated,pole.pole_number,pole.internal_id)
    except ValueError as exc:
        raise HTTPException(500,'Saved workbook could not be reopened') from exc
    result.update({'project_id':project_id,'version_id':version.id,'snapshot_file_id':file_id,
                   'geojson_match':geojson_match,'download_available':True,'editable':True,
                   'internal_id_editable':has_permission(u,'workbook.edit_internal_id')})
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
    rows=visible_annotations(db,u,project_id).order_by(ProductionAnnotation.created_at,ProductionAnnotation.id).all()
    return [annotation_dict(row) for row in rows]

@app.get('/api/projects/{project_id}/production-annotations.geojson')
def download_production_annotations_geojson(project_id:str,u:User=Depends(require_permission('project.read')),db:Session=Depends(get_db)):
    project=db.query(Project).filter_by(id=project_id).first()
    if not project: raise HTTPException(404,'Project not found')
    rows=visible_annotations(db,u,project_id).order_by(ProductionAnnotation.created_at,ProductionAnnotation.id).all()
    document=annotations_feature_collection(db,project,rows)
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
    # Children (attachments/equipment on a crossarm, guys on an anchor) record their parent; everything else hangs from the pole.
    parent=resolve_parent(db,row.project_id,body.family,body.pole_internal_id,body.reference_annotation_id)
    vertical,horizontal,distance=measurement_values(db,row.project_id,body.x,body.y,body.z,body.reference_annotation_id)
    latitude,longitude=project_to_wgs84(project.crs,body.x,body.y)
    row.block_name=body.block_name; row.family=body.family; row.feature_type=body.feature_type
    row.x=body.x; row.y=body.y; row.z=body.z; row.latitude=latitude; row.longitude=longitude; row.pole_internal_id=body.pole_internal_id; row.reference_annotation_id=body.reference_annotation_id
    row.vertical_delta=vertical; row.horizontal_offset=horizontal; row.distance_3d=distance
    row.attributes_json=json.dumps({**body.attributes,**parent_attributes(body.family,parent)},default=str); row.status=body.status
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
    if body.reference_annotation_id: visible_annotation(db,u,project_id,body.reference_annotation_id)
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
    return _update_production_annotation(project_id,annotation_id,body,u,db)

def _update_production_annotation(project_id:str,annotation_id:str,body:ProductionAnnotationIn,u:User,db:Session,action:str='UPDATE_PRODUCTION_ANNOTATION',extra:dict|None=None):
    row=visible_annotation(db,u,project_id,annotation_id)
    if body.reference_annotation_id==row.id: raise HTTPException(422,'An annotation cannot reference itself')
    if body.reference_annotation_id: visible_annotation(db,u,project_id,body.reference_annotation_id)
    if body.family in SEQUENCED_ANNOTATION_GROUPS:
        if body.pole_internal_id is None: raise HTTPException(422,'Select a Pole Number before saving this annotation group')
        pole_lock=db.query(Pole).filter_by(project_id=project_id,internal_id=body.pole_internal_id).with_for_update().first()
        if not pole_lock: raise HTTPException(422,'Selected pole does not belong to this project workbook')
        feature_type=(row.feature_type if row.family==body.family and row.pole_internal_id==body.pole_internal_id
                      else next_annotation_feature_type(db,project_id,body.pole_internal_id,body.family,exclude_annotation_id=row.id))
        body=body.model_copy(update={'feature_type':feature_type})
    _claim_annotation_revision(db,u,row,body.expected_revision)
    before=annotation_dict(row); previous_pole_id=row.pole_internal_id
    _clear_pole_verification_for_annotation(db,project_id,row.id,previous_pole_id)
    _apply_production_annotation(row,body,u.email,db); row.modified_by=u.email
    db.add(AuditLog(actor=u.email,action=action,entity_type='production_annotation',entity_id=row.id,detail_json=json.dumps({'before':before,'feature_type':row.feature_type,**(extra or {})},default=str)))
    db.commit(); db.refresh(row); return annotation_dict(row)

POINT_HISTORY_ACTIONS=('CREATE_PRODUCTION_ANNOTATION','UPDATE_PRODUCTION_ANNOTATION','RESTORE_PRODUCTION_ANNOTATION')

@app.get('/api/projects/{project_id}/production-annotations/{annotation_id}/history')
def production_annotation_history(project_id:str,annotation_id:str,u:User=Depends(require_permission('project.read')),db:Session=Depends(get_db)):
    row=visible_annotation(db,u,project_id,annotation_id)
    hidden=hidden_authors(db,u); users={x.email:x for x in db.query(User).all()}
    def who(email):
        if email in hidden: return 'an admin'
        user=users.get(email); return (user.username or user.name or email) if user else email
    entries=(db.query(AuditLog).filter(AuditLog.entity_type=='production_annotation',AuditLog.entity_id==row.id,AuditLog.action.in_(POINT_HISTORY_ACTIONS))
        .order_by(AuditLog.created_at.desc(),AuditLog.id.desc()).all())
    out=[]
    for entry in entries:
        try: detail=json.loads(entry.detail_json or '{}')
        except ValueError: detail={}
        before=detail.get('before')
        # Each edit stored the version it replaced; that earlier version is what "Restore" brings back.
        out.append({'audit_id':entry.id,'action':entry.action,'by':who(entry.actor),'at':iso_utc(entry.created_at),
                    'restored_from':detail.get('restored_from'),
                    'previous':None if not before else {'feature_type':before.get('feature_type'),'family':before.get('family'),'status':before.get('status'),
                        'coordinates':before.get('coordinates'),'pole_internal_id':before.get('pole_internal_id'),'attributes':before.get('attributes') or {},
                        'saved_by':who(before.get('modified_by')),'saved_at':before.get('updated_at'),'revision':before.get('revision')}})
    return {'annotation':annotation_dict(row),'current_by':who(row.modified_by),'entries':out}

class AnnotationRestoreIn(BaseModel):
    audit_id:int; expected_revision:int|None=Field(default=None,ge=1)

@app.post('/api/projects/{project_id}/production-annotations/{annotation_id}/restore')
def restore_production_annotation(project_id:str,annotation_id:str,body:AnnotationRestoreIn,u:User=Depends(require_permission('production.annotate')),db:Session=Depends(get_db)):
    visible_annotation(db,u,project_id,annotation_id)
    entry=db.query(AuditLog).filter(AuditLog.id==body.audit_id,AuditLog.entity_type=='production_annotation',AuditLog.entity_id==annotation_id,
        AuditLog.action.in_(('UPDATE_PRODUCTION_ANNOTATION','RESTORE_PRODUCTION_ANNOTATION'))).first()
    before=json.loads(entry.detail_json or '{}').get('before') if entry else None
    if not before: raise HTTPException(404,"That version is not in this point's history")
    if entry.actor in hidden_authors(db,u) or before.get('modified_by') in hidden_authors(db,u): raise HTTPException(404,"That version is not in this point's history")
    coords=before.get('coordinates') or {}
    restored=ProductionAnnotationIn(block_name=before['block_name'],family=before['family'],feature_type=before['feature_type'],
        x=coords['x'],y=coords['y'],z=coords['z'],pole_internal_id=before.get('pole_internal_id'),reference_annotation_id=before.get('reference_annotation_id'),
        attributes=before.get('attributes') or {},status=before.get('status') or 'IN_PROGRESS',expected_revision=body.expected_revision)
    return _update_production_annotation(project_id,annotation_id,restored,u,db,action='RESTORE_PRODUCTION_ANNOTATION',extra={'restored_from':entry.id})

def _claim_annotation_revision(db:Session,u:User,row:ProductionAnnotation,expected:int|None):
    # Atomic compare-and-set: only one of two concurrent saves of the same revision can succeed.
    current=row.revision or 1
    claimed=(db.query(ProductionAnnotation)
        .filter(ProductionAnnotation.id==row.id,ProductionAnnotation.revision==(expected if expected is not None else current))
        .update({ProductionAnnotation.revision:ProductionAnnotation.revision+1},synchronize_session=False))
    if claimed!=1:
        db.rollback(); db.refresh(row)
        editor='another user' if row.modified_by in hidden_authors(db,u) else row.modified_by
        raise HTTPException(409,f'{row.feature_type} was changed by {editor} after you opened it. Your change was not saved; the latest version has been reloaded.')

@app.delete('/api/projects/{project_id}/production-annotations/{annotation_id}')
def delete_production_annotation(project_id:str,annotation_id:str,expected_revision:int|None=Query(None,ge=1),u:User=Depends(require_permission('production.annotate')),db:Session=Depends(get_db)):
    row=visible_annotation(db,u,project_id,annotation_id)
    dependents=[d.feature_type for d in db.query(ProductionAnnotation).filter_by(project_id=project_id,reference_annotation_id=row.id).order_by(ProductionAnnotation.feature_type).all()]
    if dependents: raise HTTPException(409,f"{row.feature_type} is the parent of {', '.join(dependents)}. Move or delete those points first.")
    _claim_annotation_revision(db,u,row,expected_revision)
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
    # Validate before retiring anything: an Excel the Production import cannot read must not replace the working one.
    try:
        # ignore_cleanup_errors: on Windows the workbook reader can still hold the file when the folder is removed.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            candidate=pathlib.Path(folder)/'replacement.xlsx'; candidate.write_bytes(read_bytes(rec.object_key))
            parse_workbook(str(candidate),p.crs)
    except Exception as exc:
        rec.status='REJECTED'
        db.add(AuditLog(actor=u.email,action='REJECT_PRODUCTION_WORKBOOK',entity_type='project',entity_id=project_id,detail_json=json.dumps({'file_id':rec.id,'filename':rec.filename,'reason':str(exc)[:500]})))
        db.commit()
        raise HTTPException(400,f'This Excel cannot be imported: {str(exc).splitlines()[0][:300]}. The current Excel was kept.')
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

def rule_coverage_summary(runs):
    """Which QC rules the latest successful run could apply to this workbook, so "no findings" is never mistaken for a pass."""
    done=[r for r in runs if r.status=='SUCCEEDED' and r.finished_at]
    if not done: return None
    run=max(done,key=lambda r: r.finished_at)
    try: summary=json.loads(run.summary_json or '{}')
    except ValueError: return None
    rules=summary.get('rules')
    if not isinstance(rules,list): return None  # runs made before coverage was recorded
    return {'qc_run_id':run.id,'finished_at':iso_utc(run.finished_at),'pole_sheet':summary.get('pole_sheet'),'rules':rules,
            'ran':sum(1 for r in rules if r.get('applicable')),'total':len(rules)}

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
                'source_project':{'id':source.id,'name':source.name} if source else None,
                'rule_coverage':rule_coverage_summary(runs)}
    return {**production,'project_id':project_id,'project_status':p.status,'poles':len(poles),'poles_pass':sum(x.qc_status=='PASS' for x in poles),'poles_fail':sum(x.qc_status=='FAIL' for x in poles),'poles_review':sum(x.qc_status=='REVIEW' for x in poles),'poles_unverifiable':sum(x.qc_status=='UNVERIFIABLE' for x in poles),'findings':len(fs),'fail':sum(x.severity=='FAIL' for x in fs),'review':sum(x.severity=='REVIEW' for x in fs),'unverifiable':sum(x.severity=='UNVERIFIABLE' for x in fs),'open_findings':sum(x.status=='OPEN' for x in fs)}
@app.get('/api/projects/{project_id}/poles')
def poles(project_id:str,u:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.query(Pole).filter_by(project_id=project_id).order_by(Pole.internal_id).all()
    project=db.query(Project).filter_by(id=project_id).first()
    # Workbook lat/lon expressed in the project CRS so the viewer can navigate to poles not yet verified in LiDAR.
    try: locations={location['internal_id']:location for location in pole_locations(project,rows)} if project and rows else {}
    except Exception: locations={}
    hidden=hidden_annotation_ids(db,u,project_id)
    return [{**visible_pole_dict(p,hidden),'workbook_x':locations.get(p.internal_id,{}).get('workbook_x'),
             'workbook_y':locations.get(p.internal_id,{}).get('workbook_y'),'workbook_z':locations.get(p.internal_id,{}).get('workbook_z')} for p in rows]
@app.get('/api/projects/{project_id}/findings')
def findings(project_id:str,severity:str|None=None,internal_id:int|None=None,status:str|None=None,u:User=Depends(current_user),db:Session=Depends(get_db)):
    q=db.query(Finding).filter_by(project_id=project_id)
    if severity:q=q.filter(Finding.severity==severity)
    if internal_id:q=q.filter(Finding.internal_id==internal_id)
    if status:q=q.filter(Finding.status==status)
    return [finding_dict(f) for f in q.order_by(Finding.internal_id,Finding.id).all()]
@app.get('/api/projects/{project_id}/poles/{internal_id}/scene')
def scene(project_id:str,internal_id:int,request:Request,include_related:bool=Query(True),u:User=Depends(current_user),db:Session=Depends(get_db)):
    p=db.query(Pole).filter_by(project_id=project_id,internal_id=internal_id).first()
    if not p: raise HTTPException(404,'Pole not found')
    fs=db.query(Finding).filter_by(project_id=project_id,internal_id=internal_id).all(); related=sorted(set(x for f in fs for x in json.loads(f.related_poles_json or '[]'))); ids=[internal_id]+(related if include_related else [])
    feats=db.query(SceneFeature).filter(SceneFeature.project_id==project_id,SceneFeature.internal_id.in_(ids)).all(); selected=db.query(Pole).filter(Pole.project_id==project_id,Pole.internal_id.in_(ids)).all(); names=sorted(set(x.block_name for x in selected if x.block_name)); blocks=[]
    for b in db.query(LidarBlock).filter(LidarBlock.project_id==project_id,LidarBlock.name.in_(names)).all(): blocks.append({'name':b.name,'bbox':[b.x_min,b.y_min,b.x_max,b.y_max],'copc_url':block_url(b.object_key,str(request.base_url)),'object_key':b.object_key,'point_count':b.point_count})
    return {'project_id':project_id,'pole':visible_pole_dict(p,hidden_annotation_ids(db,u,project_id)),'related_poles':related,'block':next((b for b in blocks if b['name']==p.block_name),None),'blocks':blocks,'features':[json.loads(x.payload_json) for x in feats],'findings':[finding_dict(f) for f in fs]}

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
    already_open=db.query(CorrectionRequest.id).filter_by(finding_id=f.id,status='OPEN').first() is not None
    row=create_correction(db,f,u.email,body.comment); db.commit()
    if not already_open: safely(notify_correction_requested,db,f,body.comment,u.email)
    return {'id':row.id,'status':row.status,'finding_id':row.finding_id}

@app.post('/api/corrections/{correction_id}/resolve')
def close_correction(correction_id:str,u:User=Depends(require_permission('correction.resolve')),db:Session=Depends(get_db)):
    row=resolve_correction(db,correction_id,u.email); db.commit()
    pole_number,internal_id=_correction_pole(db,row)
    safely(notify_correction_resolved,db,row,pole_number,internal_id,u.email)
    return {'id':row.id,'status':row.status}

def _correction_pole(db:Session,row)->tuple[str|None,int|None]:
    # Findings are rebuilt per QC run; fall back to the snapshot kept with the version.
    f=db.query(Finding).filter_by(id=row.finding_id).first()
    if f: return f.pole_number,f.internal_id
    snap=db.query(FindingRevision).filter_by(finding_id=row.finding_id).order_by(FindingRevision.id.desc()).first()
    data=json.loads(snap.snapshot_json or '{}') if snap else {}
    return data.get('pole_number'),data.get('internal_id')

@app.post('/api/projects/{project_id}/versions/{version_id}/approve')
def approve_dataset(project_id:str,version_id:str,u:User=Depends(require_permission('version.approve')),db:Session=Depends(get_db)):
    row=approve_version(db,project_id,version_id,u.email); db.commit()
    project=db.query(Project).filter_by(id=project_id).first()
    # Freeze the deliverable package as approved. A failure never undoes the approval: it is built on first download.
    try:
        build_package(db,project,row,u.email,at_approval=True); db.commit()
    except Exception:
        db.rollback(); logging.getLogger(__name__).exception('Deliverable package build failed for %s v%s',project_id,row.version_no)
    safely(notify_version_approved,db,project,row.version_no,u.email)
    db.refresh(row); return version_dict(row)

@app.get('/api/projects/{project_id}/versions/{version_id}/deliverable')
def deliverable_package(project_id:str,version_id:str,request:Request,u:User=Depends(require_permission('workspace.delivery')),db:Session=Depends(get_db)):
    project=db.query(Project).filter_by(id=project_id).first()
    version=db.query(DatasetVersion).filter_by(id=version_id,project_id=project_id).first()
    if not project or not version: raise HTTPException(404,'Dataset version not found')
    if version.status!='APPROVED': raise HTTPException(409,'Approve this version before downloading its deliverable package')
    manifest=ensure_package(db,project,version,u.email)
    db.add(AuditLog(actor=u.email,action='DOWNLOAD_DELIVERABLE_PACKAGE',entity_type='dataset_version',entity_id=version.id,detail_json=json.dumps({'package_key':manifest['package_key']})))
    db.commit()
    # Presigned (S3) or local URL: the ZIP is never proxied through the API process.
    return {**{k:manifest.get(k) for k in ('package','version_no','approved_by','approved_at','generated_at','built_at_approval','package_sha256','package_bytes')},
            'files':[{'path':f['path'],'bytes':f['bytes'],'description':f['description']} for f in manifest.get('files',[])],'url':block_url(manifest['package_key'],str(request.base_url))}

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
