import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_dynamic_api.db")
os.environ.setdefault("STORAGE_MODE", "local")
os.environ.setdefault("LOCAL_STORAGE_ROOT", "./test-storage")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@jsan.local")
os.environ.setdefault("ADMIN_PASSWORD", "ChangeMe123!")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import hash_password
from app.db import SessionLocal, get_db, initialize_schema
from app.main import app
from app.models import AuditLog, LidarBlock, Pole, Project, User

PASSWORD = "Session-Test-Password-1!"


def _user(role="USER", password=PASSWORD):
    initialize_schema()
    marker = uuid.uuid4().hex[:8]
    email = f"{role.lower()}-{marker}@example.invalid"
    db = SessionLocal()
    try:
        db.add(User(email=email, username=f"S{marker}", name=f"Session {marker}", role=role, password_hash=hash_password(password)))
        db.commit()
    finally:
        db.close()
    return email


def _login(client, name, password=PASSWORD):
    response = client.post("/api/auth/login", json={"email": name, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _user_id(client, admin, email):
    return next(row["id"] for row in client.get("/api/users", headers=admin).json() if row["email"] == email)


def test_changing_your_password_ends_other_sign_ins_but_keeps_this_one():
    email = _user()
    with TestClient(app) as client:
        laptop = _login(client, email)
        phone = _login(client, email)
        changed = client.post("/api/auth/change-password", headers=laptop, json={"current_password": PASSWORD, "new_password": "Brand-New-Password-2!"})
        assert changed.status_code == 200
        fresh = {"Authorization": f"Bearer {changed.json()['token']}"}
        assert client.get("/api/auth/me", headers=fresh).status_code == 200
        for stale in (laptop, phone):
            ended = client.get("/api/projects", headers=stale)
            assert ended.status_code == 401 and ended.json()["detail"] == "session_ended"


def test_admin_password_reset_ends_existing_sign_ins():
    email = _user()
    with TestClient(app) as client:
        admin = _login(client, "admin@jsan.local", "ChangeMe123!")
        session = _login(client, email)
        assert client.get("/api/projects", headers=session).status_code == 200
        reset = client.put(f"/api/users/{_user_id(client, admin, email)}", headers=admin, json={"password": "Temporary-Reset-Pass-3!"})
        assert reset.status_code == 200
        assert client.get("/api/projects", headers=session).status_code == 401


def test_deactivation_requires_admin_and_blocks_the_account_until_reactivated():
    email, other_email = _user(), _user()
    with TestClient(app) as client:
        admin = _login(client, "admin@jsan.local", "ChangeMe123!")
        session = _login(client, email)
        other = _login(client, other_email)
        target = f"/api/users/{_user_id(client, admin, email)}"

        assert client.put(target, json={"active": False}).status_code == 401
        assert client.put(target, headers=other, json={"active": False}).status_code == 403

        deactivated = client.put(target, headers=admin, json={"active": False})
        assert deactivated.status_code == 200 and deactivated.json()["active"] is False
        assert client.get("/api/projects", headers=session).status_code == 401
        refused = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert refused.status_code == 403 and "deactivated" in refused.json()["detail"]
        # A wrong password on a deactivated account still reads as a plain failed sign-in.
        assert client.post("/api/auth/login", json={"email": email, "password": "wrong-password"}).status_code == 401

        reactivated = client.put(target, headers=admin, json={"active": True})
        assert reactivated.status_code == 200 and reactivated.json()["active"] is True
        assert client.get("/api/projects", headers=_login(client, email)).status_code == 200

        db = SessionLocal()
        try:
            actions = {row.action for row in db.query(AuditLog).filter(AuditLog.entity_id == str(reactivated.json()["id"])).all()}
            assert {"DEACTIVATE_USER", "REACTIVATE_USER"} <= actions
        finally:
            db.close()


def test_admin_cannot_deactivate_themselves_or_remove_the_last_active_admin(tmp_path):
    # Admin accounts are managed by super admins, so the protections are exercised by a super admin.
    engine = create_engine(f"sqlite:///{tmp_path / 'admins.db'}", connect_args={"check_same_thread": False})
    initialize_schema(engine)
    Isolated = sessionmaker(bind=engine)
    db = Isolated()
    db.add_all([
        User(email="first@example.invalid", name="First", role="SUPER_ADMIN", password_hash=hash_password(PASSWORD)),
        User(email="second@example.invalid", name="Second", role="SUPER_ADMIN", password_hash=hash_password(PASSWORD)),
    ])
    db.commit()
    first_id, second_id = (db.query(User.id).filter_by(email=e).scalar() for e in ("first@example.invalid", "second@example.invalid"))
    db.close()

    def isolated_db():
        session = Isolated()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = isolated_db
    try:
        with TestClient(app) as client:
            first = _login(client, "first@example.invalid")
            assert client.put(f"/api/users/{first_id}", headers=first, json={"active": False}).status_code == 409
            assert client.put(f"/api/users/{second_id}", headers=first, json={"active": False}).status_code == 200
            # first is now the only active super admin: it cannot demote itself.
            last = client.put(f"/api/users/{first_id}", headers=first, json={"role": "USER"})
            assert last.status_code == 409 and "super admin" in last.json()["detail"]
            assert client.put(f"/api/users/{second_id}", headers=first, json={"active": True}).status_code == 200
            assert client.put(f"/api/users/{second_id}", headers=first, json={"role": "USER"}).status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_saving_or_deleting_a_point_someone_else_changed_is_refused():
    initialize_schema()
    marker = uuid.uuid4().hex[:8]
    project_id = f"conflict-{marker}"
    db = SessionLocal()
    try:
        db.add(Project(id=project_id, name="Conflict", customer="PLA", crs="EPSG:4326", units="degree", status="LIDAR_READY"))
        db.add(LidarBlock(project_id=project_id, name="tile-01", source_object_key=f"{project_id}/s.laz", object_key=f"{project_id}/t.copc.laz",
                          point_count=10, x_min=0, y_min=0, x_max=100, y_max=100, zmin=0, zmax=50, poles_json="[]"))
        db.add(Pole(project_id=project_id, internal_id=1, pole_number="P-001", manifest_json="{}"))
        db.commit()
    finally:
        db.close()
    first_email, second_email = _user(), _user()

    def point(z, revision=None):
        body = {"block_name": "tile-01", "family": "anchors", "feature_type": "x", "x": 10, "y": 20, "z": z, "pole_internal_id": 1}
        return body if revision is None else {**body, "expected_revision": revision}

    with TestClient(app) as client:
        first, second = _login(client, first_email), _login(client, second_email)
        url = f"/api/projects/{project_id}/production-annotations"
        created = client.post(url, headers=first, json=point(5))
        assert created.status_code == 200 and created.json()["revision"] == 1
        point_url = f"{url}/{created.json()['id']}"

        # Both users opened revision 1. The first save wins and moves the point to revision 2.
        saved = client.put(point_url, headers=first, json=point(6, 1))
        assert saved.status_code == 200 and saved.json()["revision"] == 2
        stale = client.put(point_url, headers=second, json=point(7, 1))
        assert stale.status_code == 409 and first_email in stale.json()["detail"]
        assert client.get(url, headers=second).json()[0]["coordinates"]["z"] == 6
        assert client.delete(f"{point_url}?expected_revision=1", headers=second).status_code == 409

        # With the latest revision the second user's edit goes through.
        fresh = client.put(point_url, headers=second, json=point(7, 2))
        assert fresh.status_code == 200 and fresh.json()["revision"] == 3 and fresh.json()["modified_by"] == second_email
        # Older clients that send no revision keep working.
        assert client.put(point_url, headers=first, json=point(8)).json()["revision"] == 4
        assert client.delete(f"{point_url}?expected_revision=4", headers=second).status_code == 200
