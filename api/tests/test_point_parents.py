"""Attachments and equipment hang from a crossarm, guys from an anchor; everything else from the pole."""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_dynamic_api.db")
os.environ.setdefault("STORAGE_MODE", "local")
os.environ.setdefault("LOCAL_STORAGE_ROOT", "./test-storage")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@jsan.local")
os.environ.setdefault("ADMIN_PASSWORD", "ChangeMe123!")

from fastapi.testclient import TestClient

from app.db import SessionLocal, initialize_schema
from app.main import app
from app.models import LidarBlock, Pole, Project


def _project():
    initialize_schema()
    project_id = f"parents-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        db.add(Project(id=project_id, name="Parents", customer="PLA", crs="EPSG:4326", units="degree", status="LIDAR_READY"))
        db.add(LidarBlock(project_id=project_id, name="tile-01", source_object_key=f"{project_id}/s.laz", object_key=f"{project_id}/t.copc.laz",
                          point_count=10, x_min=0, y_min=0, x_max=100, y_max=100, zmin=0, zmax=50, poles_json="[]"))
        db.add(Pole(project_id=project_id, internal_id=1, pole_number="P-001", manifest_json="{}"))
        db.add(Pole(project_id=project_id, internal_id=2, pole_number="P-002", manifest_json="{}"))
        db.commit()
    finally:
        db.close()
    return project_id


def _point(family, z, pole=1, parent=None):
    return {"block_name": "tile-01", "family": family, "feature_type": "x", "x": 10, "y": 20, "z": z,
            "pole_internal_id": pole, "reference_annotation_id": parent}


def test_catalogue_publishes_which_groups_can_have_a_parent():
    with TestClient(app) as client:
        admin = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "admin@jsan.local", "password": "ChangeMe123!"}).json()["token"]}
        groups = {g["id"]: g for g in client.get("/api/production/catalogue", headers=admin).json()["annotation_groups"]}
    assert groups["attachments_comm"]["parent_families"] == ["crossarms"]
    assert groups["attachments_util"]["parent_families"] == ["crossarms"]
    assert groups["equipment"]["parent_families"] == ["crossarms"]
    assert groups["guys"]["parent_families"] == ["anchors"]
    assert groups["crossarms"]["parent_families"] == [] and groups["sidewalk_braces"]["parent_families"] == []


def test_children_record_their_parent_and_default_to_the_pole():
    project_id = _project()
    with TestClient(app) as client:
        admin = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "admin@jsan.local", "password": "ChangeMe123!"}).json()["token"]}
        url = f"/api/projects/{project_id}/production-annotations"
        arm1 = client.post(url, headers=admin, json=_point("crossarms", 40)).json()
        arm2 = client.post(url, headers=admin, json=_point("crossarms", 38)).json()
        anchor = client.post(url, headers=admin, json=_point("anchors", 1)).json()
        other_pole_arm = client.post(url, headers=admin, json=_point("crossarms", 39, pole=2)).json()
        assert arm1["attributes"]["parent_feature_id"] == "pole" and arm2["feature_type"] == "arm_2"

        # A utility attachment on arm_2 records it and gets its height relative to that crossarm.
        util = client.post(url, headers=admin, json=_point("attachments_util", 36.5, parent=arm2["id"]))
        assert util.status_code == 200, util.text
        assert util.json()["reference_annotation_id"] == arm2["id"]
        assert util.json()["attributes"]["parent_feature_id"] == "arm_2"
        assert util.json()["measurements"]["vertical_delta"] == -1.5
        # No parent chosen: the attachment belongs to the pole.
        comm = client.post(url, headers=admin, json=_point("attachments_comm", 30)).json()
        assert comm["reference_annotation_id"] is None and comm["attributes"]["parent_feature_id"] == "pole"
        equipment = client.post(url, headers=admin, json=_point("equipment", 35, parent=arm1["id"])).json()
        assert equipment["attributes"]["parent_feature_id"] == "arm_1"
        guy = client.post(url, headers=admin, json=_point("guys", 37, parent=anchor["id"])).json()
        assert guy["attributes"]["parent_feature_id"] == "anc_1"

        # Wrong kind of parent, or a parent on another pole, is refused.
        wrong = client.post(url, headers=admin, json=_point("guys", 37, parent=arm1["id"]))
        assert wrong.status_code == 422 and "anchors" in wrong.json()["detail"]
        assert client.post(url, headers=admin, json=_point("attachments_comm", 30, parent=anchor["id"])).status_code == 422
        elsewhere = client.post(url, headers=admin, json=_point("attachments_comm", 30, parent=other_pole_arm["id"]))
        assert elsewhere.status_code == 422 and "same pole" in elsewhere.json()["detail"]

        # Re-parenting on edit updates the recorded parent; a parent with children cannot be deleted.
        moved = client.put(f"{url}/{util.json()['id']}", headers=admin, json={**_point("attachments_util", 36.5, parent=arm1["id"]), "expected_revision": 1})
        assert moved.status_code == 200 and moved.json()["attributes"]["parent_feature_id"] == "arm_1"
        blocked = client.delete(f"{url}/{arm1['id']}", headers=admin)
        assert blocked.status_code == 409 and "arm_1 is the parent of" in blocked.json()["detail"] and "util_1" in blocked.json()["detail"]
        assert client.delete(f"{url}/{arm2['id']}", headers=admin).status_code == 200

        # The parent travels with the exported GeoJSON.
        features = {f["properties"]["point_name"]: f["properties"] for f in client.get(f"{url}.geojson", headers=admin).json()["features"]}
        assert features["util_1"]["parent_feature_id"] == "arm_1" and features["comm_1"]["parent_feature_id"] == "pole"
