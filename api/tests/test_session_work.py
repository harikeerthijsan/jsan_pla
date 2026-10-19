"""Session work: admins export a dataset's work (signed, with who did it), clear exactly that, and view archives later."""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

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
from app.models import (AuditLog, LidarBlock, Pole, PoleAssignment, Project, ProductionAnnotation, ProductionMeasurement, User,
                        WorkArchive)
from tests.test_workbook_format import login

PASSWORD = "Unique-Test-Password-123!"


def setup():
    """A dataset with two poles, work by two users (points, a measurement, an assignment) and a verified pole."""
    initialize_schema()
    marker = uuid.uuid4().hex[:8]
    project_id = f"session-{marker}"
    alice, bob = f"alice-{marker}@example.invalid", f"bob-{marker}@example.invalid"
    db = SessionLocal()
    try:
        db.add(Project(id=project_id, name=f"Session {marker}", crs="EPSG:4326", units="degree", status="LIDAR_READY"))
        db.add(LidarBlock(project_id=project_id, name="tile-01", source_object_key="s", object_key="o", point_count=1,
                          x_min=0, y_min=0, x_max=100, y_max=100, zmin=0, zmax=100, poles_json="[]"))
        users = [User(email=e, name=n, role="USER", password_hash=hash_password(PASSWORD)) for e, n in ((alice, "Alice"), (bob, "Bob"))]
        db.add_all(users); db.flush()
        base_id, top_id, arm_id = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
        common = dict(project_id=project_id, block_name="tile-01", status="IN_PROGRESS", attributes_json="{}")
        db.add(ProductionAnnotation(id=base_id, family="poles", feature_type="Pole_Base", pole_internal_id=1, x=10, y=20, z=5, latitude=20, longitude=10,
                                    created_by=alice, modified_by=alice, **common))
        db.add(ProductionAnnotation(id=top_id, family="poles", feature_type="Pole_Top", pole_internal_id=1, x=10, y=20, z=40, latitude=20, longitude=10,
                                    created_by=bob, modified_by=bob, **common))
        db.add(ProductionAnnotation(id=arm_id, family="crossarms", feature_type="arm_1", pole_internal_id=2, x=30, y=40, z=30, latitude=40, longitude=30,
                                    created_by=bob, modified_by=bob, **common))
        db.add(Pole(project_id=project_id, internal_id=1, pole_number="P-1", manifest_json="{}", verified_x=10, verified_y=20, verified_lat=20, verified_lon=10,
                    verified_bottom_elevation=5, verified_top_elevation=40, verified_height=35, verified_annotation_id=base_id,
                    verified_bottom_annotation_id=base_id, verified_top_annotation_id=top_id, location_verified_by=alice,
                    location_verified_at=datetime.now(timezone.utc)))
        db.add(Pole(project_id=project_id, internal_id=2, pole_number="P-2", manifest_json="{}"))
        db.add(ProductionMeasurement(id=uuid.uuid4().hex, project_id=project_id, ax=0, ay=0, az=0, bx=3, by=4, bz=0, distance=5,
                                     created_by=alice, created_at=datetime.now(timezone.utc)))
        db.add(PoleAssignment(project_id=project_id, pole_internal_id=2, user_id=users[1].id, assigned_by="admin@jsan.local"))
        db.commit()
        return project_id, alice, bob, {"base": base_id, "top": top_id, "arm": arm_id}
    finally:
        db.close()


def auth(client, email):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["token"]}


def test_only_admins_export_and_the_archive_says_who_did_what():
    project_id, alice, bob, ids = setup()
    with TestClient(app) as client:
        url = f"/api/projects/{project_id}/work-archive"
        assert client.post(url).status_code == 401
        assert client.post(url, headers=auth(client, alice)).status_code == 403
        exported = client.post(url, headers=login(client))
        assert exported.status_code == 200 and exported.headers["content-disposition"].startswith("attachment;")
        archive = json.loads(exported.content)
    assert archive["format"] == "jsan-polegrid-work-archive" and len(archive["signature"]) == 64
    assert archive["summary"]["points"] == 3 and archive["summary"]["measurements"] == 1 and archive["summary"]["assignments"] == 1
    people = {p["email"]: p for p in archive["summary"]["people"]}
    assert people[alice]["points_created"] == 1 and people[alice]["measurements"] == 1 and people[bob]["points_created"] == 2
    point = next(p for p in archive["points"] if p["id"] == ids["top"])
    assert point["created_by"] == bob and point["created_by_name"] == "Bob" and point["pole_number"] == "P-1"
    assert archive["assignments"][0]["user_name"] == "Bob" and archive["pole_verification"][0]["height"] == 35


def test_clear_removes_exactly_the_archived_work_and_skips_later_changes():
    project_id, alice, bob, ids = setup()
    with TestClient(app) as client:
        admin = login(client)
        archive_id = client.post(f"/api/projects/{project_id}/work-archive", headers=admin).headers["x-work-archive-id"]
        db = SessionLocal()
        try:  # after the download: Bob edits arm_1, and a new point is attached to Pole_Top
            arm = db.get(ProductionAnnotation, ids["arm"]); arm.revision = (arm.revision or 1) + 1
            db.add(ProductionAnnotation(id=uuid.uuid4().hex, project_id=project_id, block_name="tile-01", family="attachments_comm", feature_type="comm_1",
                                        pole_internal_id=1, reference_annotation_id=ids["top"], x=10, y=20, z=30, created_by=bob, modified_by=bob,
                                        status="IN_PROGRESS", attributes_json="{}"))
            db.commit()
        finally:
            db.close()
        url = f"/api/projects/{project_id}/work-archive/{archive_id}/clear"
        assert client.post(url).status_code == 401
        assert client.post(url, headers=auth(client, alice)).status_code == 403
        cleared = client.post(url, headers=admin)
        assert cleared.status_code == 200, cleared.text
        result = cleared.json()
        assert result["points_deleted"] == 1 and result["measurements_deleted"] == 1 and result["assignments_deleted"] == 1
        reasons = {s["feature_type"]: s["reason"] for s in result["skipped"]}
        assert reasons == {"arm_1": "changed after the archive was downloaded", "Pole_Top": "a newer point is attached to it"}
        assert client.post(url, headers=admin).status_code == 409   # only once
    db = SessionLocal()
    try:
        remaining = {r.feature_type for r in db.query(ProductionAnnotation).filter_by(project_id=project_id).all()}
        assert remaining == {"arm_1", "Pole_Top", "comm_1"}              # Pole_Base (unchanged, no dependants) is gone
        pole = db.query(Pole).filter_by(project_id=project_id, internal_id=1).one()
        assert pole.verified_bottom_elevation is None and pole.verified_lat is None and pole.verified_top_elevation == 40
        assert db.query(ProductionMeasurement).filter_by(project_id=project_id).count() == 0
        assert db.query(PoleAssignment).filter_by(project_id=project_id).count() == 0
        assert db.query(AuditLog).filter_by(action="CLEAR_WORK_SESSION", entity_id=project_id).count() == 1
    finally:
        db.close()


def test_clear_is_refused_for_old_archives_and_other_admins():
    project_id, *_ = setup()
    with TestClient(app) as client:
        admin = login(client)
        archive_id = client.post(f"/api/projects/{project_id}/work-archive", headers=admin).headers["x-work-archive-id"]
        db = SessionLocal()
        try:
            other = f"admin2-{uuid.uuid4().hex[:6]}@example.invalid"
            db.add(User(email=other, name="Other admin", role="ADMIN", password_hash=hash_password(PASSWORD)))
            db.get(WorkArchive, archive_id).created_at = datetime.now(timezone.utc) - timedelta(hours=25)
            db.commit()
        finally:
            db.close()
        url = f"/api/projects/{project_id}/work-archive/{archive_id}/clear"
        assert client.post(url, headers=auth(client, other)).status_code == 403   # not the admin who downloaded it
        assert client.post(url, headers=admin).status_code == 409                 # older than 24 hours


def test_view_shows_an_archive_read_only_and_detects_changes():
    project_id, alice, *_ = setup()
    with TestClient(app) as client:
        admin = login(client)
        content = client.post(f"/api/projects/{project_id}/work-archive", headers=admin).content
        url = f"/api/projects/{project_id}/work-archive/view"
        assert client.post(url, files={"file": ("a.json", content)}).status_code == 401
        assert client.post(url, headers=auth(client, alice), files={"file": ("a.json", content)}).status_code == 403
        view = client.post(url, headers=admin, files={"file": ("a.json", content)})
        assert view.status_code == 200 and view.json()["verified"] and view.json()["same_project"]
        assert view.json()["summary"]["points"] == 3 and {p["created_by_name"] for p in view.json()["points"]} == {"Alice", "Bob"}
        tampered = json.loads(content); tampered["points"][0]["created_by"] = "someone-else@example.invalid"
        changed = client.post(url, headers=admin, files={"file": ("a.json", json.dumps(tampered).encode())})
        assert changed.status_code == 200 and changed.json()["verified"] is False
        assert client.post(url, headers=admin, files={"file": ("a.json", b"{\"hello\": 1}")}).status_code == 422
        assert client.post(url, headers=admin, files={"file": ("a.json", b"not json")}).status_code == 422
    db = SessionLocal()
    try:  # viewing changes nothing in the dataset
        assert db.query(ProductionAnnotation).filter_by(project_id=project_id).count() == 3
    finally:
        db.close()


def test_measurements_are_saved_with_who_measured():
    project_id, alice, *_ = setup()
    with TestClient(app) as client:
        url = f"/api/projects/{project_id}/measurements"
        assert client.get(url).status_code == 401
        user = auth(client, alice)
        created = client.post(url, headers=user, json={"a": {"x": 0, "y": 0, "z": 0}, "b": {"x": 6, "y": 8, "z": 0}})
        assert created.status_code == 200 and created.json()["distance"] == 10 and created.json()["created_by_name"] == "Alice"
        listed = client.get(url, headers=user).json()
        assert {m["distance"] for m in listed} == {5, 10}
        assert client.delete(f"{url}/{created.json()['id']}", headers=user).status_code == 200
        assert client.delete(f"{url}/missing", headers=user).status_code == 404
