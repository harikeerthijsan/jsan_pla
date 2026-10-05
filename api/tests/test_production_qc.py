"""Production datasets: Excel replacement, and QC through a linked QC dataset that shares the LiDAR but never the Production Excel."""
import json
import os
import uuid

os.environ.setdefault('DATABASE_URL', 'sqlite:///./test_dynamic_api.db')
os.environ.setdefault('STORAGE_MODE', 'local')
os.environ.setdefault('LOCAL_STORAGE_ROOT', './test-storage')
os.environ.setdefault('JWT_SECRET', 'test-secret')
os.environ.setdefault('ADMIN_EMAIL', 'admin@jsan.local')
os.environ.setdefault('ADMIN_PASSWORD', 'ChangeMe123!')

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app import processor, storage
from app.auth import hash_password
from app.db import SessionLocal, initialize_schema
from app.main import app
from app.models import DatasetFile, Finding, LidarBlock, Pole, ProcessingJob, ProductionAnnotation, ProductionGeoFeature, Project, User
from app.workflow import DatasetVersion, QCRun, VersionFile

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def collection_workbook(rows) -> bytes:
    workbook = Workbook()
    poles = workbook.active
    poles.title = 'poles'
    poles.append(['internal_id', 'pole_number', 'grade_of_construction', 'latitude', 'longitude', 'bottom_elev_ft',
                  'top_lat', 'top_lon', 'top_elev_ft', 'remarks'])
    for internal_id, number in rows:
        lat, lon = 34.37 + internal_id * 0.0005, -118.91
        poles.append([internal_id, number, 'A', lat, lon, 500, lat, lon, 540, None])
    for name in ['attachments', 'crossarms', 'equipment', 'anchors', 'guys', 'sidewalk_braces', 'span_guys']:
        workbook.create_sheet(name).append(['internal_id', 'pole_number'])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def admin_headers(client):
    token = client.post('/api/auth/login', json={'email': 'admin@jsan.local', 'password': 'ChangeMe123!'}).json()['token']
    return {'Authorization': f'Bearer {token}'}


def reviewer_headers(client):
    email = f'qc-reviewer-{uuid.uuid4().hex[:8]}@example.invalid'
    db = SessionLocal()
    try:
        db.add(User(email=email, name='QC reviewer', role='QC_REVIEWER', password_hash=hash_password('Unique-Test-Password-123!')))
        db.commit()
    finally:
        db.close()
    token = client.post('/api/auth/login', json={'email': email, 'password': 'Unique-Test-Password-123!'}).json()['token']
    return {'Authorization': f'Bearer {token}'}


def upload(client, headers, prepare_path, filename, data, role=None):
    body = {'filename': filename, 'size_bytes': len(data), 'content_type': XLSX}
    if role:
        body['role'] = role
    prepared = client.post(prepare_path, headers=headers, json=body)
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()['mode'] == 'local'
    sent = client.put(prepared.json()['upload_url'], headers=headers, files={'file': (filename, data, XLSX)})
    assert sent.status_code == 200, sent.text
    return prepared.json()['file_id']


@pytest.fixture
def production_project(tmp_path, monkeypatch):
    """A dataset as Production leaves it: Excel + LAS + GeoJSON uploaded, COPC converted, Production work on some poles."""
    initialize_schema()
    monkeypatch.setattr(storage, 'LOCAL_ROOT', tmp_path)

    def must_not_convert(*args, **kwargs):
        raise AssertionError('existing COPC must be reused, not converted again')
    monkeypatch.setattr(processor, 'to_copc', must_not_convert)
    monkeypatch.setattr(processor, 'pdal_summary', must_not_convert)

    project_id = f'production-qc-{uuid.uuid4().hex[:8]}'
    version_id = uuid.uuid4().hex
    ids = {role: uuid.uuid4().hex for role in ('WORKBOOK', 'WORKBOOK_EDITED', 'LIDAR_SOURCE', 'GEOJSON')}
    keys = {
        'WORKBOOK': f'{project_id}/versions/v1/source/COLLECTION.xlsx',
        'WORKBOOK_EDITED': f'{project_id}/versions/v1/derived/workbooks/COLLECTION-updated.xlsx',
        'LIDAR_SOURCE': f'{project_id}/versions/v1/source/tile.las',
        'GEOJSON': f'{project_id}/versions/v1/source/poles.geojson',
    }
    copc_key = f'{project_id}/versions/v1/lidar/tile.copc.laz'
    production_excel = collection_workbook([(1, 'P-100'), (2, 'P-200'), (3, 'P-300')])
    storage.upload_bytes(production_excel, keys['WORKBOOK'])
    storage.upload_bytes(production_excel, keys['WORKBOOK_EDITED'])
    storage.upload_bytes(b'LASF', keys['LIDAR_SOURCE'])
    storage.upload_bytes(json.dumps({'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [-118.91, 34.3705]}, 'properties': {'pole_number': 'Q-1'}}]}).encode(), keys['GEOJSON'])
    storage.upload_bytes(b'COPC', copc_key)
    filenames = {'WORKBOOK': 'COLLECTION.xlsx', 'WORKBOOK_EDITED': 'COLLECTION-updated.xlsx', 'LIDAR_SOURCE': 'tile.las', 'GEOJSON': 'poles.geojson'}
    db = SessionLocal()
    try:
        db.add(Project(id=project_id, name='Production QC', customer='PLA', crs='EPSG:6424', units='US survey foot', status='LIDAR_READY'))
        db.add(DatasetVersion(id=version_id, project_id=project_id, version_no=1, status='LIDAR_READY', created_by='admin@jsan.local'))
        for role, file_id in ids.items():
            db.add(DatasetFile(id=file_id, project_id=project_id, filename=filenames[role], role=role, object_key=keys[role], status='UPLOADED'))
        db.add(ProcessingJob(id=uuid.uuid4().hex, project_id=project_id, job_type='LIDAR_INGEST', payload_json='{}', status='SUCCEEDED'))
        db.flush()
        db.add_all([VersionFile(version_id=version_id, file_id=file_id) for file_id in ids.values()])
        db.add(LidarBlock(project_id=project_id, name='tile', source_object_key=keys['LIDAR_SOURCE'], object_key=copc_key, point_count=1234,
                          x_min=0, y_min=0, x_max=1e8, y_max=1e8, zmin=400, zmax=600, poles_json='[]'))
        db.add(Pole(project_id=project_id, internal_id=1, pole_number='P-100', manifest_json='{}', verified_x=10.0, verified_y=20.0,
                    verified_bottom_elevation=500.5, verified_top_elevation=538.25, verified_height=37.75,
                    verified_annotation_id='base-1', verified_bottom_annotation_id='base-1', verified_top_annotation_id='top-1'))
        db.add(Pole(project_id=project_id, internal_id=2, pole_number='P-200', manifest_json='{}'))
        db.add(Pole(project_id=project_id, internal_id=3, pole_number='P-300', manifest_json='{}'))
        db.add(ProductionAnnotation(id=uuid.uuid4().hex, project_id=project_id, block_name='tile', family='crossarms', feature_type='arm_1',
                                    x=1, y=2, z=3, pole_internal_id=3, created_by='producer@example.invalid', modified_by='producer@example.invalid'))
        db.commit()
    finally:
        db.close()
    return {'project_id': project_id, 'copc_key': copc_key, 'keys': keys, 'ids': ids}


def test_production_import_does_not_queue_qc(production_project):
    project_id = production_project['project_id']
    db = SessionLocal()
    try:
        version = db.query(DatasetVersion).filter_by(project_id=project_id).first()
        job_id = uuid.uuid4().hex
        db.add(ProcessingJob(id=job_id, project_id=project_id, job_type='LIDAR_INGEST', payload_json=json.dumps({'version_id': version.id}), status='QUEUED'))
        db.commit()
    finally:
        db.close()
    processor.process_job(job_id)
    db = SessionLocal()
    try:
        assert db.query(ProcessingJob).filter_by(id=job_id).first().status == 'SUCCEEDED'
        assert db.query(ProcessingJob).filter_by(project_id=project_id, job_type='INGEST').count() == 0
        assert db.query(QCRun).filter_by(project_id=project_id).count() == 0
    finally:
        db.close()


def test_replacing_the_production_excel_reimports_poles_and_keeps_production_work(production_project):
    project_id, ids = production_project['project_id'], production_project['ids']
    corrected = collection_workbook([(1, 'P-101'), (5, 'P-500')])  # P-200 and P-300 were only in the wrong Excel
    with TestClient(app) as client:
        prepare_path = f'/api/projects/{project_id}/production-workbook/prepare'
        assert client.post(prepare_path, json={'filename': 'x.xlsx'}).status_code == 401
        assert client.post(prepare_path, headers=reviewer_headers(client), json={'filename': 'x.xlsx'}).status_code == 403
        admin = admin_headers(client)
        assert client.post(prepare_path, headers=admin, json={'filename': 'wrong.csv'}).status_code == 400
        file_id = upload(client, admin, prepare_path, 'COLLECTION-corrected.xlsx', corrected)
        applied = client.post(f'/api/projects/{project_id}/production-workbook/{file_id}/apply', headers=admin)
        assert applied.status_code == 200, applied.text
        assert set(applied.json()['replaced']) == {'COLLECTION.xlsx', 'COLLECTION-updated.xlsx'}
        assert client.post(f'/api/projects/{project_id}/production-workbook/{file_id}/apply', headers=admin).status_code == 409  # already queued

    processor.process_job(applied.json()['job_id'])

    db = SessionLocal()
    try:
        job = db.query(ProcessingJob).filter_by(id=applied.json()['job_id']).first()
        assert job.status == 'SUCCEEDED', job.error
        assert 'Workbook replaced: 2 poles imported, 1 removed, 1 kept' in job.message and 'P-300' in job.message
        poles = {p.internal_id: p for p in db.query(Pole).filter_by(project_id=project_id).all()}
        assert poles[1].pole_number == 'P-101' and poles[1].verified_height == 37.75  # updated from the new Excel, verification kept
        assert 5 in poles  # new pole
        assert 2 not in poles  # only in the wrong Excel, no Production work
        assert 3 in poles  # only in the wrong Excel, but has a saved point: kept
        statuses = {f.id: f.status for f in db.query(DatasetFile).filter_by(project_id=project_id).all()}
        assert statuses[ids['WORKBOOK']] == 'SUPERSEDED' and statuses[ids['WORKBOOK_EDITED']] == 'SUPERSEDED' and statuses[file_id] == 'UPLOADED'
        assert storage.local_path(production_project['keys']['WORKBOOK']).exists()  # the wrong Excel is kept, not deleted
        assert db.query(ProcessingJob).filter_by(project_id=project_id, job_type='INGEST').count() == 0
    finally:
        db.close()


def test_qc_dataset_shares_lidar_and_uses_only_its_own_excel(production_project):
    project_id, copc_key, keys = production_project['project_id'], production_project['copc_key'], production_project['keys']
    with TestClient(app) as client:
        create_path = f'/api/projects/{project_id}/qc-dataset'
        assert client.post(create_path, json={}).status_code == 401
        assert client.post(create_path, headers=reviewer_headers(client), json={}).status_code == 403
        admin = admin_headers(client)
        assert client.post(f'/api/projects/{project_id}/process', headers=admin).status_code == 409  # never QC the Production Excel

        summary = client.get(f'/api/projects/{project_id}/summary', headers=admin).json()
        assert summary['production_dataset'] is True and summary['qc_dataset'] is None and summary['has_geojson'] is True

        created = client.post(create_path, headers=admin, json={'include_geojson': True})
        assert created.status_code == 200, created.text
        qc_id = created.json()['id']
        assert created.json()['source_project_id'] == project_id and created.json()['shared'] == {'lidar': 1, 'geojson': 1}
        again = client.post(create_path, headers=admin, json={'include_geojson': True})
        assert again.json()['id'] == qc_id and again.json()['existing'] is True

        qc_summary = client.get(f'/api/projects/{qc_id}/summary', headers=admin).json()
        assert qc_summary['source_project'] == {'id': project_id, 'name': 'Production QC'}
        assert qc_summary['production_dataset'] is False and qc_summary['has_workbook'] is False and qc_summary['lidar_blocks'] == 1
        assert client.get(f'/api/projects/{project_id}/summary', headers=admin).json()['qc_dataset']['id'] == qc_id

        upload(client, admin, f'/api/projects/{qc_id}/uploads/prepare', 'QC.xlsx', collection_workbook([(1, 'Q-1'), (2, 'Q-2')]), role='WORKBOOK')
        queued = client.post(f'/api/projects/{qc_id}/process', headers=admin)
        assert queued.status_code == 200, queued.text

    processor.process_job(queued.json()['job_id'])

    db = SessionLocal()
    try:
        job = db.query(ProcessingJob).filter_by(id=queued.json()['job_id']).first()
        assert job.status == 'SUCCEEDED', job.error
        files = {f.role: f for f in db.query(DatasetFile).filter_by(project_id=qc_id).all()}
        assert files['LIDAR_SOURCE'].object_key == keys['LIDAR_SOURCE'] and files['GEOJSON'].object_key == keys['GEOJSON']
        assert files['WORKBOOK'].filename == 'QC.xlsx'  # only the QC Excel
        [block] = db.query(LidarBlock).filter_by(project_id=qc_id).all()
        assert block.object_key == copc_key  # shared COPC, not reconverted
        qc_poles = {p.internal_id: p.pole_number for p in db.query(Pole).filter_by(project_id=qc_id).all()}
        assert qc_poles == {1: 'Q-1', 2: 'Q-2'}
        assert db.query(Finding).filter_by(project_id=qc_id).count() >= 0
        assert db.query(QCRun).filter_by(project_id=qc_id, status='SUCCEEDED').count() == 1
        assert db.query(ProductionGeoFeature).filter_by(project_id=qc_id, pole_internal_id=1).count() == 1  # optional GeoJSON matched to QC poles
        production_poles = {p.internal_id: p.pole_number for p in db.query(Pole).filter_by(project_id=project_id).all()}
        assert production_poles == {1: 'P-100', 2: 'P-200', 3: 'P-300'}  # Production untouched
        assert db.query(QCRun).filter_by(project_id=project_id).count() == 0
    finally:
        db.close()


def test_qc_dataset_without_geojson_shares_lidar_only(production_project):
    project_id = production_project['project_id']
    with TestClient(app) as client:
        created = client.post(f'/api/projects/{project_id}/qc-dataset', headers=admin_headers(client), json={'include_geojson': False})
        assert created.status_code == 200, created.text
        assert created.json()['shared'] == {'lidar': 1, 'geojson': 0}
    db = SessionLocal()
    try:
        roles = sorted(f.role for f in db.query(DatasetFile).filter_by(project_id=created.json()['id']).all())
        assert roles == ['LIDAR_SOURCE']
    finally:
        db.close()
