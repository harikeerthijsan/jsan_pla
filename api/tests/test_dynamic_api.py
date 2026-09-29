import os
os.environ.setdefault('DATABASE_URL','sqlite:///./test_dynamic_api.db')
os.environ.setdefault('STORAGE_MODE','local')
os.environ.setdefault('LOCAL_STORAGE_ROOT','./test-storage')
os.environ.setdefault('JWT_SECRET','test-secret')
os.environ.setdefault('ADMIN_EMAIL','admin@jsan.local')
os.environ.setdefault('ADMIN_PASSWORD','ChangeMe123!')
from fastapi.testclient import TestClient
from app.main import app


def test_create_dynamic_project_and_prepare_upload():
    with TestClient(app) as c:
        token=c.post('/api/auth/login',json={'email':'admin@jsan.local','password':'ChangeMe123!'}).json()['token']
        h={'Authorization':f'Bearer {token}'}
        p=c.post('/api/projects',headers=h,json={'name':'Dynamic Sample 9','customer':'PLA','crs':'EPSG:6424','units':'US survey foot'})
        assert p.status_code==200; pid=p.json()['id']
        u=c.post(f'/api/projects/{pid}/uploads/prepare',headers=h,json={'filename':'COLLECTION.xlsx','role':'WORKBOOK','size_bytes':1234,'content_type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'})
        assert u.status_code==200
        assert u.json()['mode']=='local'
        assert '/uploads/' in u.json()['upload_url']


def test_analysis_frame_and_section_job_queue():
    import json, uuid
    from app.db import SessionLocal
    from app.models import Project, Pole, SceneFeature
    project_id='profile-'+uuid.uuid4().hex[:8]
    db=SessionLocal()
    try:
        db.add(Project(id=project_id,name='Profile Test',customer='PLA',crs='EPSG:6424',units='US survey foot',status='READY_FOR_REVIEW'))
        db.add(Pole(project_id=project_id,internal_id=1,pole_number='P1',qc_status='PASS',qc_fail=0,qc_review=0,qc_unverifiable=0,manifest_json='{}'))
        db.add(Pole(project_id=project_id,internal_id=2,pole_number='P2',qc_status='PASS',qc_fail=0,qc_review=0,qc_unverifiable=0,manifest_json='{}'))
        for pid,x in [(1,1000.0),(2,1100.0)]:
            feat={'type':'Feature','properties':{'feature_type':'pole','internal_id':pid},'geometry':{'type':'LineString','coordinates':[[x,2000.0,500.0],[x,2000.0,540.0]]}}
            db.add(SceneFeature(project_id=project_id,internal_id=pid,feature_type='pole',payload_json=json.dumps(feat)))
        db.commit()
    finally:
        db.close()
    with TestClient(app) as c:
        token=c.post('/api/auth/login',json={'email':'admin@jsan.local','password':'ChangeMe123!'}).json()['token']
        h={'Authorization':f'Bearer {token}'}
        r=c.get(f'/api/projects/{project_id}/poles/1/analysis-frame?target_internal_id=2',headers=h)
        assert r.status_code==200
        assert round(r.json()['frame']['length'],3)==100.0
        q=c.post(f'/api/projects/{project_id}/poles/1/sections/prepare',headers=h,json={'target_internal_id':2,'width':12,'depth':12,'resolution':1,'max_points':5000})
        assert q.status_code==200
        assert q.json()['cached'] is False
        j=c.get('/api/jobs/'+q.json()['job_id'],headers=h)
        assert j.json()['job_type']=='SECTION'
