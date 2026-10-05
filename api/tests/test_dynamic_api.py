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


def test_lidar_only_production_job_does_not_require_workbook():
    import uuid
    from app.db import SessionLocal
    from app.models import DatasetFile, ProcessingJob

    with TestClient(app) as c:
        token=c.post('/api/auth/login',json={'email':'admin@jsan.local','password':'ChangeMe123!'}).json()['token']
        h={'Authorization':f'Bearer {token}'}
        p=c.post('/api/projects',headers=h,json={'name':f'Production {uuid.uuid4().hex[:8]}','customer':'PLA','crs':'EPSG:6424','units':'US survey foot'})
        assert p.status_code==200; pid=p.json()['id']
        prepared=c.post(f'/api/projects/{pid}/uploads/prepare',headers=h,json={'filename':'tile-01.laz','role':'LIDAR_SOURCE','size_bytes':100,'content_type':'application/octet-stream'})
        assert prepared.status_code==200
        db=SessionLocal()
        try:
            file_row=db.query(DatasetFile).filter_by(id=prepared.json()['file_id']).first()
            file_row.status='UPLOADED'; db.commit()
        finally:
            db.close()

        queued=c.post(f'/api/projects/{pid}/process-lidar',headers=h)
        assert queued.status_code==200,queued.text
        db=SessionLocal()
        try:
            job=db.query(ProcessingJob).filter_by(id=queued.json()['job_id']).first()
            assert job.job_type=='LIDAR_INGEST'
            assert job.status=='QUEUED'
        finally:
            db.close()


def test_qc_reviewer_cannot_queue_lidar_production():
    import uuid
    from app.auth import hash_password
    from app.db import SessionLocal
    from app.models import Project, User

    marker=uuid.uuid4().hex[:8]
    email=f'production-denied-{marker}@example.invalid'
    db=SessionLocal()
    try:
        db.add(User(email=email,name='QC only',role='QC_REVIEWER',password_hash=hash_password('Unique-Test-Password-123!')))
        db.add(Project(id=f'production-denied-{marker}',name='Denied',customer='PLA',crs='EPSG:6424',units='US survey foot',status='UPLOADING'))
        db.commit()
    finally:
        db.close()
    with TestClient(app) as c:
        token=c.post('/api/auth/login',json={'email':email,'password':'Unique-Test-Password-123!'}).json()['token']
        denied=c.post(f'/api/projects/production-denied-{marker}/process-lidar',headers={'Authorization':f'Bearer {token}'})
        assert denied.status_code==403


def test_production_annotations_are_typed_measured_audited_and_role_protected():
    import uuid
    from app.auth import hash_password
    from app.db import SessionLocal
    from app.models import AuditLog, LidarBlock, Pole, Project, User

    marker=uuid.uuid4().hex[:8]
    project_id=f'annotation-{marker}'
    qc_email=f'annotation-qc-{marker}@example.invalid'
    db=SessionLocal()
    try:
        db.add(Project(id=project_id,name='Annotation Test',customer='PLA',crs='EPSG:4326',units='degree',status='LIDAR_READY'))
        db.add(LidarBlock(project_id=project_id,name='tile-01',source_object_key=f'{project_id}/source.laz',object_key=f'{project_id}/tile-01.copc.laz',point_count=100,x_min=0,y_min=0,x_max=100,y_max=100,zmin=90,zmax=140,poles_json='[]'))
        db.add(Pole(project_id=project_id,internal_id=1,pole_number='P-001',corrected_lat=20.001,corrected_lon=10.001,manifest_json='{}'))
        db.add(Pole(project_id=project_id,internal_id=2,pole_number='P-002',corrected_lat=20.002,corrected_lon=10.002,manifest_json='{}'))
        db.add(User(email=qc_email,name='QC annotation test',role='QC_REVIEWER',password_hash=hash_password('Unique-Test-Password-123!')))
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        assert client.get(f'/api/projects/{project_id}/production-annotations').status_code==401
        assert client.get(f'/api/projects/{project_id}/production-annotations.geojson').status_code==401
        admin_token=client.post('/api/auth/login',json={'email':'admin@jsan.local','password':'ChangeMe123!'}).json()['token']
        admin={'Authorization':f'Bearer {admin_token}'}
        catalogue=client.get('/api/production/catalogue',headers=admin)
        assert catalogue.status_code==200
        assert any('Pole Base / Ground Point' in family['point_types'] for family in catalogue.json()['families'])
        groups={group['id']:group for group in catalogue.json()['annotation_groups']}
        # Numbered groups have no upper limit, so they publish a prefix instead of a fixed list.
        for family,prefix in (('crossarms','arm'),('attachments_comm','comm'),('attachments_util','util'),('anchors','anc'),('other_poles','other')):
            assert groups[family]['automatic_numbering'] is True
            assert groups[family]['prefix']==prefix and groups[family]['point_types']==[]
            assert 'max_count' not in groups[family]
        assert groups['poles']['point_types']==['Pole_Base','Pole_Top']
        assert groups['poles']['automatic_numbering'] is False

        first_anchor=client.post(f'/api/projects/{project_id}/production-annotations',headers=admin,json={
            'block_name':'tile-01','family':'anchors','feature_type':'client-preview',
            'x':11,'y':21,'z':101,'pole_internal_id':1,
        })
        second_anchor=client.post(f'/api/projects/{project_id}/production-annotations',headers=admin,json={
            'block_name':'tile-01','family':'anchors','feature_type':'client-preview',
            'x':12,'y':22,'z':102,'pole_internal_id':1,
        })
        other_pole_anchor=client.post(f'/api/projects/{project_id}/production-annotations',headers=admin,json={
            'block_name':'tile-01','family':'anchors','feature_type':'client-preview',
            'x':13,'y':23,'z':103,'pole_internal_id':2,
        })
        assert first_anchor.status_code==second_anchor.status_code==other_pole_anchor.status_code==200
        assert first_anchor.json()['feature_type']=='anc_1'
        assert second_anchor.json()['feature_type']=='anc_2'
        assert other_pole_anchor.json()['feature_type']=='anc_1'

        preserved_anchor=client.put(f"/api/projects/{project_id}/production-annotations/{first_anchor.json()['id']}",headers=admin,json={
            'block_name':'tile-01','family':'anchors','feature_type':'anc_99',
            'x':11.5,'y':21.5,'z':101.5,'pole_internal_id':1,
        })
        assert preserved_anchor.status_code==200
        assert preserved_anchor.json()['feature_type']=='anc_1'

        # No per-pole cap: keep adding past the former limit of six anchors.
        extra_anchor_ids=[]
        for index in range(3,10):
            extra=client.post(f'/api/projects/{project_id}/production-annotations',headers=admin,json={
                'block_name':'tile-01','family':'anchors','feature_type':'client-preview',
                'x':11+index,'y':21,'z':101,'pole_internal_id':1,
            })
            assert extra.status_code==200,extra.text
            assert extra.json()['feature_type']==f'anc_{index}'
            extra_anchor_ids.append(extra.json()['id'])
        for annotation_id in extra_anchor_ids:
            assert client.delete(f'/api/projects/{project_id}/production-annotations/{annotation_id}',headers=admin).status_code==200
        invalid_number=client.put(f"/api/projects/{project_id}/production-annotations/{second_anchor.json()['id']}",headers=admin,json={
            'block_name':'tile-01','family':'crossarms','feature_type':'arm_0',
            'x':12,'y':22,'z':102,'pole_internal_id':1,
        })
        assert invalid_number.status_code==200 and invalid_number.json()['feature_type']=='arm_1'  # server assigns the number

        base=client.post(f'/api/projects/{project_id}/production-annotations',headers=admin,json={
            'block_name':'tile-01','family':'poles','feature_type':'Pole_Base',
            'x':10,'y':20,'z':100,'pole_internal_id':1,'attributes':{},'status':'IN_PROGRESS',
        })
        assert base.status_code==200,base.text
        assert base.json()['geographic_coordinates']=={'latitude':20.0,'longitude':10.0}
        assert base.json()['pole_internal_id']==1
        base_id=base.json()['id']

        transformed=client.post(f'/api/projects/{project_id}/coordinates/to-wgs84',headers=admin,json={'x':10,'y':20,'z':100})
        assert transformed.status_code==200
        assert transformed.json()['latitude']==20.0
        assert transformed.json()['longitude']==10.0

        top=client.post(f'/api/projects/{project_id}/production-annotations',headers=admin,json={
            'block_name':'tile-01','family':'poles','feature_type':'Pole_Top',
            'x':10.1,'y':20.1,'z':130,'pole_internal_id':1,'status':'COMPLETED',
        })
        assert top.status_code==200,top.text
        verified_pole=next(p for p in client.get(f'/api/projects/{project_id}/poles',headers=admin).json() if p['internal_id']==1)
        assert verified_pole['verified_bottom_elevation']==100.0
        assert verified_pole['verified_top_elevation']==130.0
        assert verified_pole['verified_height']==30.0

        attachment=client.post(f'/api/projects/{project_id}/production-annotations',headers=admin,json={
            'block_name':'tile-01','family':'Electrical / Communication Attachment Points','feature_type':'Communication Attachment Points',
            'x':13,'y':24,'z':112,'reference_annotation_id':base_id,'pole_internal_id':1,
            'attributes':{'pole_internal_id':'1','owner':'TEST COMM','support':'J-Hook'},'status':'COMPLETED',
        })
        assert attachment.status_code==200,attachment.text
        measured=attachment.json()['measurements']
        assert measured=={'vertical_delta':12.0,'horizontal_offset':5.0,'distance_3d':13.0}

        exported=client.get(f'/api/projects/{project_id}/production-annotations.geojson',headers=admin)
        assert exported.status_code==200,exported.text
        assert exported.headers['content-type'].startswith('application/geo+json')
        assert exported.headers['content-disposition'].endswith('-annotation-points.geojson"')
        collection=exported.json()
        assert collection['type']=='FeatureCollection'
        assert collection['feature_count']==6
        assert len(collection['features'])==6
        base_feature=next(feature for feature in collection['features'] if feature['id']==base_id)
        assert base_feature['geometry']=={'type':'Point','coordinates':[10.0,20.0,100.0]}
        assert base_feature['properties']['pole_number']=='P-001'
        assert base_feature['properties']['point_name']=='Pole_Base'
        assert base_feature['properties']['project_crs']=='EPSG:4326'

        invalid=client.post(f'/api/projects/{project_id}/production-annotations',headers=admin,json={
            'block_name':'tile-01','family':'Pole Points','feature_type':'Anchor Point','x':1,'y':2,'z':3,
        })
        assert invalid.status_code==422

        qc_token=client.post('/api/auth/login',json={'email':qc_email,'password':'Unique-Test-Password-123!'}).json()['token']
        denied=client.post(f'/api/projects/{project_id}/production-annotations',headers={'Authorization':f'Bearer {qc_token}'},json={
            'block_name':'tile-01','family':'poles','feature_type':'Pole_Top','x':10,'y':20,'z':130,
        })
        assert denied.status_code==403

        assert client.delete(f'/api/projects/{project_id}/production-annotations/{base_id}',headers=admin).status_code==409
        assert client.delete(f"/api/projects/{project_id}/production-annotations/{attachment.json()['id']}",headers=admin).status_code==200
        assert client.delete(f"/api/projects/{project_id}/production-annotations/{top.json()['id']}",headers=admin).status_code==200
        assert client.delete(f'/api/projects/{project_id}/production-annotations/{base_id}',headers=admin).status_code==200

    db=SessionLocal()
    try:
        actions=[x.action for x in db.query(AuditLog).filter(AuditLog.entity_type=='production_annotation').all()]
        assert 'CREATE_PRODUCTION_ANNOTATION' in actions
        assert 'DELETE_PRODUCTION_ANNOTATION' in actions
        pole=db.query(Pole).filter_by(project_id=project_id,internal_id=1).first()
        assert pole.verified_lat is None  # deleting the verification point clears the current verified location
        assert db.query(AuditLog).filter_by(action='VERIFY_POLE_LOCATION',entity_id=f'{project_id}:1').first()
        assert db.query(AuditLog).filter_by(action='VERIFY_POLE_ELEVATION',entity_id=f'{project_id}:1').first()
    finally:
        db.close()


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
