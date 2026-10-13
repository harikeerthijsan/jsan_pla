"""Moving a saved point: new X/Y/Z, latitude/longitude recomputed by the server, attributes kept, move audited."""
import os
import uuid
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_dynamic_api.db")
os.environ.setdefault("STORAGE_MODE", "local")
os.environ.setdefault("LOCAL_STORAGE_ROOT", "./test-storage")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@jsan.local")
os.environ.setdefault("ADMIN_PASSWORD", "ChangeMe123!")

from fastapi.testclient import TestClient

from app.auth import hash_password
from app.db import SessionLocal, initialize_schema
from app.main import app
from app.models import LidarBlock, Pole, Project, User

ROOT = Path(__file__).resolve().parents[2]


def setup_project():
    initialize_schema()
    marker = uuid.uuid4().hex[:8]
    project_id, qc_email = f"move-{marker}", f"move-qc-{marker}@example.invalid"
    db = SessionLocal()
    try:
        # EPSG:4326 keeps the expected latitude/longitude obvious: x is longitude, y is latitude.
        db.add(Project(id=project_id, name="Move test", customer="PLA", crs="EPSG:4326", units="degree", status="LIDAR_READY"))
        db.add(LidarBlock(project_id=project_id, name="tile-01", source_object_key=f"{project_id}/source.laz", object_key=f"{project_id}/tile-01.copc.laz",
                          point_count=100, x_min=0, y_min=0, x_max=100, y_max=100, zmin=90, zmax=140, poles_json="[]"))
        db.add(Pole(project_id=project_id, internal_id=1, pole_number="P-001", corrected_lat=20.001, corrected_lon=10.001, manifest_json="{}"))
        db.add(User(email=qc_email, name="QC move test", role="QC_REVIEWER", password_hash=hash_password("Unique-Test-Password-123!")))
        db.commit()
    finally:
        db.close()
    return project_id, qc_email


def move_body(saved, x, y, z, placement="lidar"):
    """What the Move point tool sends: the saved point unchanged except its position and placement."""
    return {"block_name": saved["block_name"], "family": saved["family"], "feature_type": saved["feature_type"], "x": x, "y": y, "z": z,
            "pole_internal_id": saved["pole_internal_id"], "reference_annotation_id": saved["reference_annotation_id"],
            "attributes": {**saved["attributes"], "placement": placement}, "status": saved["status"], "expected_revision": saved["revision"]}


def test_moving_a_point_updates_coordinates_and_recomputes_lat_lon():
    project_id, qc_email = setup_project()
    url = f"/api/projects/{project_id}/production-annotations"
    with TestClient(app) as client:
        admin = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "admin@jsan.local", "password": "ChangeMe123!"}).json()["token"]}
        saved = client.post(url, headers=admin, json={"block_name": "tile-01", "family": "anchors", "feature_type": "client-preview", "x": 11, "y": 21, "z": 101,
                                                      "pole_internal_id": 1, "attributes": {"placement": "lidar", "remarks": "keep me"}}).json()
        body = move_body(saved, 15.25, 24.5, 98.75, placement="view_plane")
        # Unauthenticated and read-only roles cannot move points.
        assert client.put(f"{url}/{saved['id']}", json=body).status_code == 401
        qc = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": qc_email, "password": "Unique-Test-Password-123!"}).json()["token"]}
        assert client.put(f"{url}/{saved['id']}", headers=qc, json=body).status_code == 403

        moved = client.put(f"{url}/{saved['id']}", headers=admin, json=body)
        assert moved.status_code == 200, moved.text
        m = moved.json()
        assert m["coordinates"] == {"x": 15.25, "y": 24.5, "z": 98.75}
        assert abs(m["geographic_coordinates"]["longitude"] - 15.25) < 1e-9 and abs(m["geographic_coordinates"]["latitude"] - 24.5) < 1e-9
        assert m["feature_type"] == saved["feature_type"] and m["attributes"]["remarks"] == "keep me" and m["attributes"]["placement"] == "view_plane"
        assert m["revision"] == saved["revision"] + 1
        # A second move based on the stale revision is refused rather than silently overwriting.
        assert client.put(f"{url}/{saved['id']}", headers=admin, json=move_body(saved, 16, 25, 99)).status_code == 409
        history = client.get(f"{url}/{saved['id']}/history", headers=admin)
        assert history.status_code == 200 and len(history.json()) >= 2


def test_the_point_menu_offers_move_point():
    pick = (ROOT / "web" / "assets" / "modules" / "production-pick.js").read_text(encoding="utf-8")
    assert 'data-point-action="move">Move point</button>' in pick
    assert "export function startProductionMove(row)" in pick and "export async function moveSavedPoint(row,spot)" in pick
    assert "pickOrPlace(e.clientX-r.left,e.clientY-r.top,annotationPickOptions())" in pick and "expected_revision:row.revision" in pick
