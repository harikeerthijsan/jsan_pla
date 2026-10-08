import json
import os
import uuid

os.environ.setdefault('DATABASE_URL', 'sqlite:///./test_dynamic_api.db')
os.environ.setdefault('STORAGE_MODE', 'local')
os.environ.setdefault('LOCAL_STORAGE_ROOT', './test-storage')
os.environ.setdefault('JWT_SECRET', 'test-secret')
os.environ.setdefault('ADMIN_EMAIL', 'admin@jsan.local')
os.environ.setdefault('ADMIN_PASSWORD', 'ChangeMe123!')

import pytest
from fastapi.testclient import TestClient
from pyproj import Transformer

from app.geojson_import import GeoJSONError, import_project_geojson, match_to_poles, parse_features
from app.main import app


@pytest.fixture(scope='module', autouse=True)
def migrated_database():
    from app.db import initialize_schema
    initialize_schema()


PROJECT_CRS = 'EPSG:6424'  # NAD83(2011) California zone 5, US survey foot
TO_PROJECT = Transformer.from_crs('EPSG:4326', PROJECT_CRS, always_xy=True)
POLE_1 = (-118.9140, 34.3470)
POLE_2 = (-118.9120, 34.3480)


def project_xy(lon, lat):
    return TO_PROJECT.transform(lon, lat)


def point(lon, lat, **properties):
    return {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [lon, lat]}, 'properties': properties}


def collection(*features, crs=None):
    document = {'type': 'FeatureCollection', 'features': list(features)}
    if crs:
        document['crs'] = {'type': 'name', 'properties': {'name': crs}}
    return json.dumps(document)


def poles():
    return [
        {'internal_id': 1, 'pole_number': 'P-001', 'x': project_xy(*POLE_1)[0], 'y': project_xy(*POLE_1)[1]},
        {'internal_id': 2, 'pole_number': 'P-002', 'x': project_xy(*POLE_2)[0], 'y': project_xy(*POLE_2)[1]},
    ]


def test_wgs84_points_are_transformed_explicitly_and_matched_by_pole_number():
    crs, features = parse_features(collection(point(*POLE_1, POLE_NO='P-001', OBJECTID=7), point(*POLE_2, POLE_NO='p-002 ')), PROJECT_CRS)
    assert crs == 'OGC:CRS84'
    expected = project_xy(*POLE_1)
    assert features[0]['x'] == pytest.approx(expected[0], abs=1e-6)
    assert features[0]['y'] == pytest.approx(expected[1], abs=1e-6)
    assert features[0]['source_geometry']['coordinates'] == list(POLE_1)

    summary = match_to_poles(features, poles(), 'US survey foot')
    assert summary['match_property'] == 'POLE_NO' and summary['match_target'] == 'pole_number'
    assert [f['pole_internal_id'] for f in features] == [1, 2]
    assert {f['match_method'] for f in features} == {'ID'}
    assert features[0]['match_distance'] == pytest.approx(0, abs=1e-6)


def test_numeric_property_matches_internal_id():
    _, features = parse_features(collection(point(*POLE_2, pole_id=2.0)), PROJECT_CRS)
    summary = match_to_poles(features, poles(), 'US survey foot')
    assert summary['match_target'] == 'internal_id'
    assert features[0]['pole_internal_id'] == 2 and features[0]['match_method'] == 'ID'


def test_both_identifiers_must_select_the_same_pole_and_point_z_is_preserved():
    first = point(*POLE_1, POLE_NO='P-001', InternalID=1)
    first['geometry']['coordinates'].append(515.25)
    _, features = parse_features(collection(first, point(*POLE_2, POLE_NO='P-001', InternalID=2)), PROJECT_CRS)
    summary = match_to_poles(features, poles(), 'US survey foot')
    assert features[0]['z'] == pytest.approx(515.25)
    assert features[0]['geometry']['coordinates'][2] == pytest.approx(515.25)
    assert features[0]['pole_internal_id'] == 1 and features[0]['match_method'] == 'ID'
    assert features[1]['pole_internal_id'] is None and features[1]['match_method'] == 'CONFLICT'
    assert summary['identity_conflicts'] == 1


def test_coincidental_objectid_far_from_the_pole_is_not_an_id_match():
    far = (POLE_1[0] + 0.05, POLE_1[1])  # ~4.6 km east
    _, features = parse_features(collection(point(*far, OBJECTID=1)), PROJECT_CRS)
    summary = match_to_poles(features, poles(), 'US survey foot')
    assert summary['match_property'] is None
    assert features[0]['pole_internal_id'] is None
    assert summary['unmatched_points'] == 1


def test_nearest_pole_fallback_respects_tolerance():
    x, y = project_xy(*POLE_1)
    near = {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [x + 3, y + 4]}, 'properties': {'name': 'no id'}}
    far = {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [x + 30, y]}, 'properties': {'name': 'no id'}}
    _, features = parse_features(collection(near, far, crs='urn:ogc:def:crs:EPSG::6424'), PROJECT_CRS)
    summary = match_to_poles(features, poles(), 'US survey foot')
    assert features[0]['x'] == pytest.approx(x + 3)  # same CRS: no transformation
    assert features[0]['match_method'] == 'NEAREST' and features[0]['pole_internal_id'] == 1
    assert features[0]['match_distance'] == pytest.approx(5.0)
    assert features[1]['pole_internal_id'] is None
    assert summary['matched_nearest'] == 1 and summary['unmatched_points'] == 1


def test_lines_and_polygons_are_kept_but_not_matched():
    line = {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': [list(POLE_1), list(POLE_2)]}, 'properties': {'POLE_NO': 'P-001'}}
    _, features = parse_features(collection(line), PROJECT_CRS)
    match_to_poles(features, poles(), 'US survey foot')
    assert features[0]['geometry_type'] == 'LineString'
    assert len(features[0]['geometry']['coordinates']) == 2
    assert features[0]['pole_internal_id'] is None


@pytest.mark.parametrize('raw,message', [
    ('not json', 'not valid UTF-8 JSON'),
    (json.dumps({'type': 'Topology'}), 'FeatureCollection'),
    (collection({'type': 'Feature', 'geometry': {'type': 'Circle', 'coordinates': [0, 0]}, 'properties': {}}), 'unsupported geometry'),
    (collection(point('a', 'b')), 'Invalid Point coordinates'),
    (collection(point(-200.0, 34.0)), 'out of range'),
    (collection(point(*POLE_1), crs='LOCAL_GRID'), 'Unsupported GeoJSON CRS'),
])
def test_invalid_geojson_is_rejected_with_a_clear_message(raw, message):
    with pytest.raises(GeoJSONError, match=message):
        parse_features(raw, PROJECT_CRS)


def _seed_project():
    from app.db import SessionLocal
    from app.models import Pole, Project

    project_id = f'geojson-{uuid.uuid4().hex[:8]}'
    db = SessionLocal()
    try:
        db.add(Project(id=project_id, name='GeoJSON Test', customer='PLA', crs=PROJECT_CRS, units='US survey foot', status='LIDAR_READY'))
        db.add(Pole(project_id=project_id, internal_id=1, pole_number='P-001', corrected_lat=POLE_1[1], corrected_lon=POLE_1[0], manifest_json='{}'))
        x, y = project_xy(*POLE_2)
        db.add(Pole(project_id=project_id, internal_id=2, pole_number='P-002', corrected_lat=POLE_2[1], corrected_lon=POLE_2[0],
                    verified_x=x + 6, verified_y=y + 8, manifest_json='{}'))
        db.commit()
    finally:
        db.close()
    return project_id


def test_import_replaces_derived_features_for_the_project():
    from app.db import SessionLocal
    from app.models import ProductionGeoFeature, Project

    project_id = _seed_project()
    db = SessionLocal()
    try:
        project = db.query(Project).filter_by(id=project_id).first()
        summary = import_project_geojson(db, project, 'file-1', collection(point(*POLE_1, POLE_NO='P-001'), point(*POLE_2, POLE_NO='P-002')))
        db.commit()
        assert summary['matched_id'] == 2 and summary['source_crs'] == 'OGC:CRS84' and summary['project_crs'] == PROJECT_CRS
        import_project_geojson(db, project, 'file-2', collection(point(*POLE_1, POLE_NO='P-001')))
        db.commit()
        rows = db.query(ProductionGeoFeature).filter_by(project_id=project_id).all()
        assert [(row.source_file_id, row.pole_internal_id) for row in rows] == [('file-2', 1)]
    finally:
        db.close()


def test_geo_feature_api_is_authenticated_and_reports_offsets():
    from app.auth import hash_password
    from app.db import SessionLocal
    from app.models import Project, User

    project_id = _seed_project()
    marker = uuid.uuid4().hex[:8]
    qc_email = f'geojson-qc-{marker}@example.invalid'
    db = SessionLocal()
    try:
        project = db.query(Project).filter_by(id=project_id).first()
        import_project_geojson(db, project, 'file-1', collection(point(*POLE_2, POLE_NO='P-002', OWNER='Utility <b>Co</b>')))
        db.add(User(email=qc_email, name='QC GeoJSON test', role='QC_REVIEWER', password_hash=hash_password('Unique-Test-Password-123!')))
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        assert client.get(f'/api/projects/{project_id}/production-geo-features').status_code == 401
        token = client.post('/api/auth/login', json={'email': 'admin@jsan.local', 'password': 'ChangeMe123!'}).json()['token']
        admin = {'Authorization': f'Bearer {token}'}
        response = client.get(f'/api/projects/{project_id}/production-geo-features', headers=admin)
        assert response.status_code == 200, response.text
        [feature] = response.json()
        assert feature['pole_internal_id'] == 2 and feature['match_method'] == 'ID'
        assert feature['properties']['OWNER'] == 'Utility <b>Co</b>'  # stored verbatim; the UI renders it as text
        assert feature['offsets']['verified'] == pytest.approx(10.0)  # verified X/Y is (+6, +8) from the GeoJSON point
        assert feature['offsets']['workbook'] == pytest.approx(0, abs=1e-6)
        assert client.get('/api/projects/missing-project/production-geo-features', headers=admin).status_code == 404
        listed = {p['internal_id']: p for p in client.get(f'/api/projects/{project_id}/poles', headers=admin).json()}
        expected = project_xy(*POLE_1)
        assert listed[1]['workbook_x'] == pytest.approx(expected[0], abs=1e-6)
        assert listed[1]['workbook_y'] == pytest.approx(expected[1], abs=1e-6)

        upload_project = client.post('/api/projects', headers=admin, json={'name': f'GeoJSON upload {marker}', 'customer': 'PLA', 'crs': PROJECT_CRS, 'units': 'US survey foot'}).json()['id']
        prepare = f'/api/projects/{upload_project}/uploads/prepare'
        ok = client.post(prepare, headers=admin, json={'filename': 'poles.geojson', 'role': 'GEOJSON', 'size_bytes': 1200, 'content_type': 'application/geo+json'})
        assert ok.status_code == 200, ok.text
        assert client.post(prepare, headers=admin, json={'filename': 'poles.json', 'role': 'GEOJSON', 'size_bytes': 1200}).status_code == 200
        assert client.post(prepare, headers=admin, json={'filename': 'poles.txt', 'role': 'GEOJSON', 'size_bytes': 10}).status_code == 400
        assert client.post(prepare, headers=admin, json={'filename': 'poles.geojson', 'role': 'GEOJSON', 'size_bytes': 10**12}).status_code == 413

        qc_token = client.post('/api/auth/login', json={'email': qc_email, 'password': 'Unique-Test-Password-123!'}).json()['token']
        denied = client.post(prepare, headers={'Authorization': f'Bearer {qc_token}'}, json={'filename': 'poles.geojson', 'role': 'GEOJSON', 'size_bytes': 1200})
        assert denied.status_code == 403
