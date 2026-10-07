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
from app.models import Finding, LidarBlock, Pole, PolePresence, ProcessingJob, Project, User

PASSWORD = "Team-Test-Password-1!"


def _user(role="USER"):
    marker = uuid.uuid4().hex[:8]
    email = f"team-{role.lower()}-{marker}@example.invalid"
    db = SessionLocal()
    try:
        db.add(User(email=email, username=f"T{marker}", name=f"Team {marker}", role=role, password_hash=hash_password(PASSWORD)))
        db.commit()
        return email, db.query(User.id).filter_by(email=email).scalar()
    finally:
        db.close()


def _login(client, email, password=PASSWORD):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _production_dataset(with_qc=False):
    """A Production dataset (it has a LIDAR_INGEST job) with poles P-001..P-004 and optionally its QC dataset."""
    initialize_schema()
    marker = uuid.uuid4().hex[:8]
    project_id = f"team-{marker}"
    db = SessionLocal()
    try:
        db.add(Project(id=project_id, name="Team", customer="PLA", crs="EPSG:4326", units="degree", status="LIDAR_READY"))
        db.add(ProcessingJob(id=uuid.uuid4().hex, project_id=project_id, job_type="LIDAR_INGEST", payload_json="{}", status="SUCCEEDED", progress=100, stage="done"))
        db.add(LidarBlock(project_id=project_id, name="tile-01", source_object_key=f"{project_id}/s.laz", object_key=f"{project_id}/t.copc.laz",
                          point_count=10, x_min=0, y_min=0, x_max=100, y_max=100, zmin=0, zmax=50, poles_json="[]"))
        for n in range(1, 5):
            db.add(Pole(project_id=project_id, internal_id=n, pole_number=f"P-00{n}", manifest_json="{}"))
        if with_qc:
            qc_id = f"{project_id}-qc"
            db.add(Project(id=qc_id, name="Team QC", customer="PLA", crs="EPSG:4326", units="degree", status="READY_FOR_QC", source_project_id=project_id))
            for n in range(1, 5):
                db.add(Pole(project_id=qc_id, internal_id=n, pole_number=f"P-00{n}", manifest_json="{}"))
            db.add(Finding(id=f"f-{marker}", project_id=qc_id, internal_id=2, pole_number="P-002", rule_id="PLA-R001", severity="FAIL",
                           sheet="poles", field="x", message="bad", related_poles_json="[]", status="OPEN"))
        db.commit()
    finally:
        db.close()
    return project_id


def _point(pole, feature, z=10, family="poles"):
    return {"block_name": "tile-01", "family": family, "feature_type": feature, "x": 10 + pole, "y": 20, "z": z, "pole_internal_id": pole}


def test_only_admins_assign_poles_and_everyone_sees_the_assignee():
    project_id = _production_dataset()
    user_email, user_id = _user()
    other_email, _ = _user()
    with TestClient(app) as client:
        admin = _login(client, "admin@jsan.local", "ChangeMe123!")
        user = _login(client, user_email)
        url = f"/api/projects/{project_id}/pole-assignments"
        body = {"user_id": user_id, "pole_internal_ids": [1, 2, 3]}

        assert client.put(url, json=body).status_code == 401
        assert client.put(url, headers=user, json=body).status_code == 403
        assert client.put(url, headers=admin, json={"user_id": user_id, "pole_internal_ids": [1, 99]}).status_code == 422
        assigned = client.put(url, headers=admin, json=body)
        assert assigned.status_code == 200
        assert [(row["pole_internal_id"], row["user_id"]) for row in assigned.json()] == [(1, user_id), (2, user_id), (3, user_id)]

        # Reassigning one pole replaces its assignee; unassigning clears it.
        _, second_id = _user()
        client.put(url, headers=admin, json={"user_id": second_id, "pole_internal_ids": [3]})
        assert client.put(url, headers=admin, json={"user_id": None, "pole_internal_ids": [2]}).status_code == 200
        seen = {row["pole_internal_id"]: row["user_id"] for row in client.get(url, headers=_login(client, other_email)).json()}
        assert seen == {1: user_id, 3: second_id}

        # Deactivated accounts cannot receive work.
        client.put(f"/api/users/{second_id}", headers=admin, json={"active": False})
        assert client.put(url, headers=admin, json={"user_id": second_id, "pole_internal_ids": [4]}).status_code == 422


def test_presence_shows_who_has_a_pole_open_but_never_admins_to_users():
    project_id = _production_dataset()
    first_email, _ = _user()
    second_email, _ = _user()
    with TestClient(app) as client:
        admin = _login(client, "admin@jsan.local", "ChangeMe123!")
        first, second = _login(client, first_email), _login(client, second_email)
        url = f"/api/projects/{project_id}/presence"
        assert client.post(url, json={"pole_internal_id": 1}).status_code == 401

        assert client.post(url, headers=first, json={"pole_internal_id": 1}).json() == []
        client.post(url, headers=admin, json={"pole_internal_id": 2})
        seen = client.post(url, headers=second, json={"pole_internal_id": 3}).json()
        assert [row["pole_internal_id"] for row in seen] == [1]
        # Admins see everyone, including users.
        assert {row["pole_internal_id"] for row in client.post(url, headers=admin, json={"pole_internal_id": 2}).json()} == {1, 3}

        # Leaving the pole clears it; a stale heartbeat stops showing.
        client.post(url, headers=first, json={"pole_internal_id": None})
        db = SessionLocal()
        try:
            db.query(PolePresence).filter_by(project_id=project_id).update({PolePresence.last_seen: datetime.now(timezone.utc) - timedelta(minutes=5)})
            db.commit()
        finally:
            db.close()
        assert client.post(url, headers=admin, json={"pole_internal_id": 2}).json() == []


def test_team_progress_credits_completion_points_and_qc_failures():
    project_id = _production_dataset(with_qc=True)
    first_email, first_id = _user()
    second_email, _ = _user()
    with TestClient(app) as client:
        admin = _login(client, "admin@jsan.local", "ChangeMe123!")
        first, second = _login(client, first_email), _login(client, second_email)
        url = f"/api/projects/{project_id}/production-annotations"
        client.put(f"/api/projects/{project_id}/pole-assignments", headers=admin, json={"user_id": first_id, "pole_internal_ids": [1, 2]})
        # Pole 1: first does base and top. Pole 2: first base, second top (second completes it). Pole 3: base only.
        for headers, body in ((first, _point(1, "Pole_Base")), (first, _point(1, "Pole_Top", 40)), (first, _point(2, "Pole_Base")),
                              (second, _point(2, "Pole_Top", 41)), (second, _point(3, "Pole_Base"))):
            assert client.post(url, headers=headers, json=body).status_code == 200
        anchor = client.post(url, headers=first, json=_point(1, "x", 12, family="anchors")).json()
        client.put(f"{url}/{anchor['id']}", headers=first, json={**_point(1, "x", 13, family="anchors"), "expected_revision": 1})

        progress_url = f"/api/projects/{project_id}/team-progress?days=7"
        assert client.get(progress_url).status_code == 401
        assert client.get(progress_url, headers=first).status_code == 403
        report = client.get(progress_url, headers=admin)
        assert report.status_code == 200, report.text
        data = report.json()
        assert len(data["days"]) == 7 and data["poles_total"] == 4 and data["poles_completed"] == 2 and data["qc"]
        rows = {row["email"]: row for row in data["users"]}
        assert rows[first_email]["assigned"] == 2
        assert rows[first_email]["completed_total"] == 1 and rows[first_email]["completed_by_day"][-1] == 1
        assert rows[first_email]["points_period"] == 4 and rows[first_email]["edits_period"] == 1
        assert rows[second_email]["completed_total"] == 1 and rows[second_email]["points_period"] == 2
        # P-002 has a FAIL finding in the linked QC dataset and was completed by the second user.
        assert (rows[second_email]["qc_checked"], rows[second_email]["qc_failed"], rows[second_email]["qc_fail_rate"]) == (1, 1, 1.0)
        assert (rows[first_email]["qc_checked"], rows[first_email]["qc_failed"], rows[first_email]["qc_fail_rate"]) == (1, 0, 0.0)
        # Opening it on the QC dataset resolves to the same Production dataset.
        assert client.get(f"/api/projects/{project_id}-qc/team-progress", headers=admin).json()["production"]["id"] == project_id


def test_point_history_and_restore_bring_back_an_earlier_version():
    project_id = _production_dataset()
    first_email, _ = _user()
    second_email, _ = _user()
    with TestClient(app) as client:
        admin = _login(client, "admin@jsan.local", "ChangeMe123!")
        first, second = _login(client, first_email), _login(client, second_email)
        url = f"/api/projects/{project_id}/production-annotations"
        created = client.post(url, headers=first, json={**_point(1, "x", 10, family="anchors"), "attributes": {}}).json()
        point_url = f"{url}/{created['id']}"
        client.put(point_url, headers=second, json={**_point(1, "x", 20, family="anchors"), "expected_revision": 1})
        client.put(point_url, headers=admin, json={**_point(1, "x", 30, family="anchors"), "expected_revision": 2})

        assert client.get(f"{point_url}/history").status_code == 401
        history = client.get(f"{point_url}/history", headers=first).json()
        assert history["annotation"]["coordinates"]["z"] == 30 and history["current_by"] == "an admin"
        actions = [entry["action"] for entry in history["entries"]]
        assert actions == ["UPDATE_PRODUCTION_ANNOTATION", "UPDATE_PRODUCTION_ANNOTATION", "CREATE_PRODUCTION_ANNOTATION"]
        admin_edit, second_edit, _ = history["entries"]
        assert admin_edit["by"] == "an admin" and admin_edit["previous"]["coordinates"]["z"] == 20
        assert second_edit["previous"]["coordinates"]["z"] == 10 and second_edit["previous"]["revision"] == 1

        # Users cannot restore a version an admin made; a stale revision is refused.
        assert client.post(f"{point_url}/restore", headers=first, json={"audit_id": admin_edit["audit_id"], "expected_revision": 3}).status_code == 404
        assert client.post(f"{point_url}/restore", headers=first, json={"audit_id": second_edit["audit_id"], "expected_revision": 2}).status_code == 409
        restored = client.post(f"{point_url}/restore", headers=first, json={"audit_id": second_edit["audit_id"], "expected_revision": 3})
        assert restored.status_code == 200 and restored.json()["coordinates"]["z"] == 10 and restored.json()["revision"] == 4
        latest = client.get(f"{point_url}/history", headers=admin).json()["entries"][0]
        assert latest["action"] == "RESTORE_PRODUCTION_ANNOTATION" and latest["restored_from"] == second_edit["audit_id"]
        assert latest["previous"]["coordinates"]["z"] == 30
