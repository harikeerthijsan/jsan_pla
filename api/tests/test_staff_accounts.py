import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_dynamic_api.db")
os.environ.setdefault("STORAGE_MODE", "local")
os.environ.setdefault("LOCAL_STORAGE_ROOT", "./test-storage")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@jsan.local")
os.environ.setdefault("ADMIN_PASSWORD", "ChangeMe123!")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import hash_password
from app.db import SessionLocal, initialize_schema
from app.main import app, validate_runtime_environment
from app.models import AuditLog, LidarBlock, Pole, Project, User
from app.seed import STAFF_ACCOUNTS, seed_staff_accounts, staff_email
from app.workbook_editor import apply_workbook_updates, inspect_workbook
from tests.test_workbook_editor import workbook_bytes
from tests.test_workbook_editor_api import create_workbook_project

SHARED = "Shared-Initial-Password-2026!"
OWN = "Own-New-Password-2026!"


def _login(client, name, password):
    response = client.post("/api/auth/login", json={"email": name, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}, response.json()["user"]


def _user(role, password=OWN, must_change=False):
    marker = uuid.uuid4().hex[:8]
    email = f"{role.lower()}-{marker}@example.invalid"
    db = SessionLocal()
    try:
        db.add(User(email=email, username=f"{role}-{marker}", name=f"{role} {marker}", role=role,
                    password_hash=hash_password(password), must_change_password=must_change))
        db.commit()
    finally:
        db.close()
    return email


def test_staff_accounts_are_seeded_once_and_never_reset(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'staff.db'}")
    initialize_schema(engine)
    db = sessionmaker(bind=engine)()
    try:
        monkeypatch.delenv("STAFF_INITIAL_PASSWORD", raising=False)
        assert seed_staff_accounts(db) == []

        monkeypatch.setenv("STAFF_INITIAL_PASSWORD", SHARED)
        created = seed_staff_accounts(db)
        assert created == ["Admin001", "Admin002"] + [f"JSAN{n:03d}" for n in range(1, 21)]
        roles = {row.username: row.role for row in db.query(User).all()}
        assert roles["Admin001"] == roles["Admin002"] == "ADMIN"
        assert all(roles[f"JSAN{n:03d}"] == "USER" for n in range(1, 21))
        assert all(row.must_change_password for row in db.query(User).all())
        assert db.query(AuditLog).filter_by(action="SEED_STAFF_ACCOUNT").count() == 22

        # A person who changed their password keeps it across restarts and secret rotations.
        jsan001 = db.query(User).filter_by(username="JSAN001").one()
        jsan001.password_hash = hash_password(OWN)
        db.commit()
        monkeypatch.setenv("STAFF_INITIAL_PASSWORD", "A-Different-Secret-2027!")
        assert seed_staff_accounts(db) == []
        assert db.query(User).count() == len(STAFF_ACCOUNTS) == 22
        from app.auth import verify_password
        assert verify_password(OWN, db.query(User).filter_by(username="JSAN001").one().password_hash)
    finally:
        db.close()


def test_production_rejects_a_weak_staff_password(monkeypatch):
    monkeypatch.setattr("app.main.APP_ENV", "production")
    monkeypatch.setattr("app.main.MODE", "s3")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/pla")
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("ADMIN_PASSWORD", "A-Strong-Admin-Password-1")
    monkeypatch.setenv("STAFF_INITIAL_PASSWORD", "short")
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    with pytest.raises(RuntimeError, match="STAFF_INITIAL_PASSWORD"):
        validate_runtime_environment()


def test_username_login_forces_a_password_change_before_any_work():
    initialize_schema()
    marker = uuid.uuid4().hex[:6]
    username = f"JSANT{marker}"
    db = SessionLocal()
    try:
        db.add(User(email=staff_email(username), username=username, name=username, role="USER",
                    password_hash=hash_password(SHARED), must_change_password=True))
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        assert client.post("/api/auth/change-password", json={"current_password": SHARED, "new_password": OWN}).status_code == 401
        assert client.post("/api/auth/login", json={"email": username, "password": "wrong-password"}).status_code == 401
        headers, user = _login(client, username.lower(), SHARED)
        assert user["username"] == username and user["must_change_password"] is True
        assert client.get("/api/auth/me", headers=headers).status_code == 200
        blocked = client.get("/api/projects", headers=headers)
        assert blocked.status_code == 403 and blocked.json()["detail"] == "password_change_required"

        wrong = client.post("/api/auth/change-password", headers=headers, json={"current_password": "not-it-at-all", "new_password": OWN})
        assert wrong.status_code == 400
        same = client.post("/api/auth/change-password", headers=headers, json={"current_password": SHARED, "new_password": SHARED})
        assert same.status_code == 400
        short = client.post("/api/auth/change-password", headers=headers, json={"current_password": SHARED, "new_password": "short"})
        assert short.status_code == 422
        changed = client.post("/api/auth/change-password", headers=headers, json={"current_password": SHARED, "new_password": OWN})
        assert changed.status_code == 200 and changed.json()["user"]["must_change_password"] is False
        assert client.get("/api/projects", headers=headers).status_code == 200
        assert client.post("/api/auth/login", json={"email": username, "password": SHARED}).status_code == 401

        profile = client.put("/api/auth/profile", headers=headers, json={"name": "Field Tech One"})
        assert profile.status_code == 200 and profile.json()["name"] == "Field Tech One"
        assert client.get("/api/auth/me", headers=headers).json()["name"] == "Field Tech One"


def test_admin_password_reset_is_temporary_and_users_cannot_manage_accounts():
    initialize_schema()
    user_email = _user("USER")
    with TestClient(app) as client:
        admin, _ = _login(client, "admin@jsan.local", "ChangeMe123!")
        user, _ = _login(client, user_email, OWN)
        assert client.get("/api/users", headers=user).status_code == 403
        listed = client.get("/api/users", headers=admin)
        assert listed.status_code == 200
        target = next(row for row in listed.json() if row["email"] == user_email)
        assert client.put(f"/api/users/{target['id']}", headers=user, json={"password": "Reset-By-User-2026!"}).status_code == 403
        reset = client.put(f"/api/users/{target['id']}", headers=admin, json={"password": "Temporary-Reset-2026!"})
        assert reset.status_code == 200 and reset.json()["must_change_password"] is True
        again, _ = _login(client, user_email, "Temporary-Reset-2026!")
        assert client.get("/api/projects", headers=again).status_code == 403


def test_only_admin_can_create_user_and_admin_accounts():
    initialize_schema()
    regular_email = _user("USER")
    marker = uuid.uuid4().hex[:8]
    temporary_password = "Temporary-Account-2026!"
    with TestClient(app) as client:
        admin, _ = _login(client, "admin@jsan.local", "ChangeMe123!")
        regular, _ = _login(client, regular_email, OWN)
        user_body = {
            "username": f"JSAN-{marker}",
            "email": f"new-user-{marker}@example.invalid",
            "name": "New Production User",
            "role": "USER",
            "password": temporary_password,
        }
        assert client.post("/api/users", json=user_body).status_code == 401
        assert client.post("/api/users", headers=regular, json=user_body).status_code == 403

        created_user = client.post("/api/users", headers=admin, json=user_body)
        assert created_user.status_code == 200, created_user.text
        assert created_user.json()["role"] == "USER"
        assert created_user.json()["must_change_password"] is True

        admin_body = {
            "username": f"ADMIN-{marker}",
            "email": f"new-admin-{marker}@example.invalid",
            "name": "New Administrator",
            "role": "ADMIN",
            "password": temporary_password,
        }
        created_admin = client.post("/api/users", headers=admin, json=admin_body)
        assert created_admin.status_code == 200, created_admin.text
        assert created_admin.json()["role"] == "ADMIN"
        assert created_admin.json()["must_change_password"] is True


def test_users_cannot_upload_or_create_datasets():
    initialize_schema()
    user_email = _user("USER")
    with TestClient(app) as client:
        admin, _ = _login(client, "admin@jsan.local", "ChangeMe123!")
        user, _ = _login(client, user_email, OWN)
        permissions = client.get("/api/workspaces", headers=user).json()
        assert permissions["workspaces"] == ["PRODUCTION", "DELIVERY", "QC"]
        assert "upload.create" not in permissions["permissions"] and "project.create" not in permissions["permissions"]
        assert "production.annotate" in permissions["permissions"]

        assert client.post("/api/projects", headers=user, json={"name": "Denied user dataset"}).status_code == 403
        created = client.post("/api/projects", headers=admin, json={"name": f"Admin dataset {uuid.uuid4().hex[:6]}"})
        assert created.status_code == 200
        project_id = created.json()["id"]
        for body in ({"filename": "a.las", "role": "LIDAR_SOURCE"}, {"filename": "a.xlsx", "role": "WORKBOOK"}, {"filename": "a.geojson", "role": "GEOJSON"}):
            assert client.post(f"/api/projects/{project_id}/uploads/prepare", headers=user, json=body).status_code == 403
        assert client.post(f"/api/projects/{project_id}/production-workbook/prepare", headers=user, json={"filename": "a.xlsx"}).status_code == 403
        assert client.post(f"/api/projects/{project_id}/qc-dataset", headers=user, json={}).status_code == 403
        assert client.post(f"/api/projects/{project_id}/process-lidar", headers=user).status_code == 403
        assert client.post(f"/api/projects/{project_id}/uploads/prepare", headers=admin, json={"filename": "a.xlsx", "role": "WORKBOOK"}).status_code == 200


def test_users_share_work_with_each_other_but_never_see_admin_work():
    initialize_schema()
    marker = uuid.uuid4().hex[:8]
    project_id = f"work-visibility-{marker}"
    db = SessionLocal()
    try:
        db.add(Project(id=project_id, name="Visibility", customer="PLA", crs="EPSG:4326", units="degree", status="LIDAR_READY"))
        db.add(LidarBlock(project_id=project_id, name="tile-01", source_object_key=f"{project_id}/s.laz", object_key=f"{project_id}/t.copc.laz",
                          point_count=10, x_min=0, y_min=0, x_max=100, y_max=100, zmin=0, zmax=50, poles_json="[]"))
        db.add(Pole(project_id=project_id, internal_id=1, pole_number="P-001", manifest_json="{}"))
        db.add(Pole(project_id=project_id, internal_id=2, pole_number="P-002", manifest_json="{}"))
        db.commit()
    finally:
        db.close()
    first_email, second_email = _user("USER"), _user("USER")

    def point(pole, feature, z):
        return {"block_name": "tile-01", "family": "poles", "feature_type": feature, "x": 10 + pole, "y": 20, "z": z, "pole_internal_id": pole}

    with TestClient(app) as client:
        admin, _ = _login(client, "admin@jsan.local", "ChangeMe123!")
        first, _ = _login(client, first_email, OWN)
        second, _ = _login(client, second_email, OWN)
        url = f"/api/projects/{project_id}/production-annotations"

        admin_point = client.post(url, headers=admin, json=point(1, "Pole_Base", 5))
        user_point = client.post(url, headers=first, json=point(2, "Pole_Base", 6))
        assert admin_point.status_code == user_point.status_code == 200
        admin_id, user_id = admin_point.json()["id"], user_point.json()["id"]

        # Admin sees everyone; users see users' work only.
        assert {row["id"] for row in client.get(url, headers=admin).json()} == {admin_id, user_id}
        assert {row["id"] for row in client.get(url, headers=second).json()} == {user_id}
        geojson = client.get(f"{url}.geojson", headers=second).json()
        assert [feature["id"] for feature in geojson["features"]] == [user_id]

        # The admin-verified pole location is hidden from users, the user-verified one is shared.
        poles = {row["internal_id"]: row for row in client.get(f"/api/projects/{project_id}/poles", headers=second).json()}
        assert poles[1]["verified_bottom_elevation"] is None and poles[1]["verified_annotation_id"] is None
        assert poles[2]["verified_bottom_elevation"] == 6
        admin_poles = {row["internal_id"]: row for row in client.get(f"/api/projects/{project_id}/poles", headers=admin).json()}
        assert admin_poles[1]["verified_bottom_elevation"] == 5

        # Another user may edit a user's point but cannot touch, reference or delete an admin's.
        edited = client.put(f"{url}/{user_id}", headers=second, json=point(2, "Pole_Base", 7))
        assert edited.status_code == 200 and edited.json()["modified_by"] == second_email
        assert client.put(f"{url}/{admin_id}", headers=second, json=point(1, "Pole_Base", 9)).status_code == 404
        assert client.delete(f"{url}/{admin_id}", headers=second).status_code == 404
        referencing = client.post(url, headers=second, json={**point(2, "Pole_Top", 30), "reference_annotation_id": admin_id})
        assert referencing.status_code == 404
        assert client.delete(f"{url}/{user_id}", headers=first).status_code == 200
        assert client.get(url, headers=admin).json()[0]["id"] == admin_id


def test_internal_id_is_read_only_for_users_in_the_workbook_editor():
    contents = workbook_bytes()
    poles = next(sheet for sheet in inspect_workbook(contents, "P-001")["worksheets"] if sheet["name"] == "poles")
    assert poles["internal_id_columns"] == [1]
    with pytest.raises(ValueError, match="internal_id can only be changed by an admin"):
        apply_workbook_updates(contents, "P-001", [{"sheet": "poles", "row": 2, "column": 1, "value": "77"}])
    updated = apply_workbook_updates(contents, "P-001", [{"sheet": "poles", "row": 2, "column": 1, "value": "77"}], allow_internal_id=True)
    assert inspect_workbook(updated, "P-001")["worksheets"][0]["rows"][0]["values"][0] == 77


def test_workbook_api_locks_internal_id_for_users_and_allows_admins(tmp_path, monkeypatch):
    project_id, _, source_id, _, _, _ = create_workbook_project(tmp_path, monkeypatch)
    user_email = _user("USER")
    with TestClient(app) as client:
        admin, _ = _login(client, "admin@jsan.local", "ChangeMe123!")
        user, _ = _login(client, user_email, OWN)
        url = f"/api/projects/{project_id}/poles/1/workbook"
        read = client.get(url, headers=user).json()
        assert read["editable"] is True and read["internal_id_editable"] is False
        assert read["worksheets"][0]["internal_id_columns"] == [1]
        denied = client.put(url, headers=user, json={"snapshot_file_id": source_id, "updates": [{"sheet": "poles", "row": 2, "column": 1, "value": "5"}]})
        assert denied.status_code == 422 and "admin" in denied.json()["detail"]
        remarks = client.put(url, headers=user, json={"snapshot_file_id": source_id, "updates": [{"sheet": "poles", "row": 2, "column": 3, "value": "User edit"}]})
        assert remarks.status_code == 200, remarks.text
        assert client.get(url, headers=admin).json()["internal_id_editable"] is True
        allowed = client.put(url, headers=admin, json={"snapshot_file_id": remarks.json()["snapshot_file_id"], "updates": [{"sheet": "poles", "row": 2, "column": 1, "value": "5"}]})
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["worksheets"][0]["rows"][0]["values"][0] == 5
