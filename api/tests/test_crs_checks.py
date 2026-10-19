"""Source CRS checks: LiDAR headers and GeoJSON must match the dataset's CRS; admins can correct a dataset's CRS."""
import json
import os
import struct
import uuid
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_dynamic_api.db")
os.environ.setdefault("STORAGE_MODE", "local")
os.environ.setdefault("LOCAL_STORAGE_ROOT", "./test-storage")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@jsan.local")
os.environ.setdefault("ADMIN_PASSWORD", "ChangeMe123!")

import pytest
from fastapi.testclient import TestClient
from pyproj import CRS

from app.auth import hash_password
from app.crs_check import crs_epsg, las_epsg
from app.db import SessionLocal
from app.geojson_import import GeoJSONError, parse_features as parse_geojson
from app.main import app
from app.models import AuditLog, ProcessingJob, Project, ProductionAnnotation, User
from tests.test_missing_internal_ids import pole_workbook
from tests.test_workbook_format import login, upload


def las_header(epsg=None, geokey=None):
    """A LAS 1.4 header (no points) with a WKT VLR (record 2112) and/or a GeoKey directory (34735)."""
    vlrs = b""
    if epsg:
        wkt = CRS.from_epsg(epsg).to_wkt("WKT1_GDAL").encode() + b"\0"
        vlrs += struct.pack("<H16sHH32s", 0, b"LASF_Projection", 2112, len(wkt), b"wkt") + wkt
    if geokey:
        keys = struct.pack("<8H", 1, 1, 0, 1, 3072, 0, 1, geokey)
        vlrs += struct.pack("<H16sHH32s", 0, b"LASF_Projection", 34735, len(keys), b"geokeys") + keys
    header = bytearray(375)
    header[0:4] = b"LASF"; header[24], header[25] = 1, 4
    struct.pack_into("<H", header, 94, 375)
    struct.pack_into("<I", header, 96, 375 + len(vlrs))
    struct.pack_into("<I", header, 100, (1 if epsg else 0) + (1 if geokey else 0))
    return bytes(header) + vlrs


def test_reads_the_crs_from_a_lidar_header():
    assert las_epsg(las_header(epsg=6426)) == 6426
    assert las_epsg(las_header(geokey=2229)) == 2229
    assert las_epsg(las_header()) is None
    with pytest.raises(ValueError):
        las_epsg(b"not a las file" * 40)
    assert crs_epsg("urn:ogc:def:crs:EPSG::6426") == 6426 and crs_epsg("nonsense") is None
    real = sorted(Path(r"D:/PLA1_Sample2/LAZ").glob("*.laz")) if Path(r"D:/PLA1_Sample2/LAZ").exists() else []
    if real:  # the customer sample (California zone 6 ftUS), when present on this machine
        from app.crs_check import header_length
        with open(real[0], "rb") as fh:
            first = fh.read(375)
            fh.seek(0)
            assert las_epsg(fh.read(header_length(first))) == 6426


def test_projected_geojson_in_another_crs_is_refused_not_converted():
    zone6 = json.dumps({"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::6426"}},
                        "features": [{"type": "Feature", "properties": {"Pole Number": "P1"}, "geometry": {"type": "Point", "coordinates": [6226373.2, 2000046.1]}}]})
    with pytest.raises(GeoJSONError, match="EPSG:6426"):
        parse_geojson(zone6, "EPSG:6424")
    assert parse_geojson(zone6, "EPSG:6426")  # same CRS: fine
    wgs84 = json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [-117.3455, 33.1502]}}]})
    assert parse_geojson(wgs84, "EPSG:6424")  # WGS84 GeoJSON is still converted, as it must be


def dataset_with_lidar(client, headers, crs, lidar_epsg):
    created = client.post("/api/projects", headers=headers, json={"name": f"CRS test {uuid.uuid4().hex[:6]}", "crs": crs, "workbook_format": "PLA-1"})
    project_id = created.json()["id"]
    upload(client, headers, project_id, "client.xlsx", "WORKBOOK", pole_workbook([[1, "P-1", 33.1502203, -117.3454951]]))
    upload(client, headers, project_id, "tile.laz", "LIDAR_SOURCE", las_header(epsg=lidar_epsg))
    return project_id


def test_processing_is_refused_when_the_lidar_is_in_another_crs():
    with TestClient(app) as client:
        headers = login(client)
        wrong = dataset_with_lidar(client, headers, "EPSG:6424", 6426)
        refused = client.post(f"/api/projects/{wrong}/process-lidar", headers=headers)
        assert refused.status_code == 422 and "EPSG:6426" in refused.json()["detail"] and "California zone 6" in refused.json()["detail"]
        right = dataset_with_lidar(client, headers, "EPSG:6426", 6426)
        assert client.post(f"/api/projects/{right}/process-lidar", headers=headers).status_code == 200


def test_admin_corrects_a_datasets_crs_and_points_are_recomputed():
    email = f"crs-user-{uuid.uuid4().hex[:6]}@example.invalid"
    db = SessionLocal()
    try:
        db.add(User(email=email, name="Production user", role="USER", password_hash=hash_password("Unique-Test-Password-123!"))); db.commit()
    finally:
        db.close()
    with TestClient(app) as client:
        admin = login(client)
        project_id = dataset_with_lidar(client, admin, "EPSG:6424", 6426)
        db = SessionLocal()
        try:  # a point saved while the CRS was wrong: its X/Y are LiDAR coordinates (zone 6), its lat/lon came out wrong
            db.add(ProductionAnnotation(id=uuid.uuid4().hex, project_id=project_id, block_name="b", family="poles", feature_type="Pole_Base",
                                        x=6226373.2, y=2000046.1, z=60, latitude=0, longitude=0, created_by="t", modified_by="t", attributes_json="{}"))
            db.commit()
        finally:
            db.close()
        url = f"/api/projects/{project_id}/crs"
        assert client.put(url, json={"crs": "EPSG:6426"}).status_code == 401
        user = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": email, "password": "Unique-Test-Password-123!"}).json()["token"]}
        assert client.put(url, headers=user, json={"crs": "EPSG:6426"}).status_code == 403
        assert client.put(url, headers=admin, json={"crs": "not-a-crs"}).status_code == 422
        contradicts = client.put(url, headers=admin, json={"crs": "EPSG:2229"})        # the LiDAR says 6426
        assert contradicts.status_code == 422 and "EPSG:6426" in contradicts.json()["detail"]
        fixed = client.put(url, headers=admin, json={"crs": "urn:ogc:def:crs:EPSG::6426"})
        assert fixed.status_code == 200, fixed.text
        body = fixed.json()
        assert body["crs"] == "EPSG:6426" and body["recomputed_points"] == 1 and body["reprocess_job_id"]
    db = SessionLocal()
    try:
        point = db.query(ProductionAnnotation).filter_by(project_id=project_id).one()
        assert abs(point.latitude - 33.1502203) < 1e-6 and abs(point.longitude - -117.3454951) < 1e-6
        assert db.query(ProcessingJob).filter_by(id=body["reprocess_job_id"], job_type="LIDAR_INGEST").count() == 1
        assert db.query(Project).filter_by(id=project_id).one().crs == "EPSG:6426"
        assert db.query(AuditLog).filter_by(action="CHANGE_PROJECT_CRS", entity_id=project_id).count() == 1
    finally:
        db.close()


def test_identify_endpoint_names_a_lidar_wkt():
    wkt = CRS.from_epsg(6426).to_wkt("WKT1_ESRI")  # ESRI-style WKT carries no EPSG ids at all
    with TestClient(app) as client:
        assert client.post("/api/crs/identify", json={"wkt": wkt}).status_code == 401
        headers = login(client)
        found = client.post("/api/crs/identify", headers=headers, json={"wkt": wkt})
        assert found.status_code == 200 and found.json()["epsg"] == 6426 and "California zone 6" in found.json()["name"]
        assert client.post("/api/crs/identify", headers=headers, json={"wkt": "PROJCS[\"made up\"]"}).status_code == 404
