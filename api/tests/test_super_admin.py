"""Super admin: oversight routes, account authority, network rules and the invisibility of super admins' work."""
import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_dynamic_api.db")
os.environ.setdefault("STORAGE_MODE", "local")
os.environ.setdefault("LOCAL_STORAGE_ROOT", "./test-storage")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@jsan.local")
os.environ.setdefault("ADMIN_PASSWORD", "ChangeMe123!")

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.auth import hash_password
from app.db import SessionLocal, initialize_schema, migration_config
from app.main import app
from app.models import AppSetting, AuditLog, LidarBlock, Pole, ProcessingJob, ProductionAnnotation, Project, User
from app.network_access import POLICY_KEY
from app.notifications import _who
from app.seed import promote_super_admins
from app.team import hidden_authors

PASSWORD = "Super-Admin-Test-Pass-1!"
OFFICE, ELSEWHERE = "52.14.20.7", "34.120.5.9"
SUPER_ROUTES = ["/api/super/people", "/api/super/activity", "/api/super/team-progress"]


def _account(role, *, remote=False):
    initialize_schema()
    marker = uuid.uuid4().hex[:8]
    email = f"sa-{role.lower()}-{marker}@example.invalid"
    db = SessionLocal()
    try:
        db.add(User(email=email, username=f"SA{role[:2]}{marker}", name=f"{role.title()} {marker}", role=role,
                    password_hash=hash_password(PASSWORD), remote_access=remote))
        db.commit()
        return email, db.query(User.id).filter_by(email=email).scalar()
    finally:
        db.close()


def _auth(client, email, ip=None):
    headers = {"X-Real-IP": ip} if ip else {}
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}, headers=headers)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}", **headers}


@pytest.fixture
def behind_proxy(monkeypatch):
    monkeypatch.setenv("CLIENT_IP_HEADER", "X-Real-IP")
    initialize_schema()
    yield
    db = SessionLocal()
    try:
        db.query(AppSetting).filter_by(key=POLICY_KEY).delete(); db.commit()
    finally:
        db.close()


def test_oversight_routes_need_a_super_admin():
    user, _ = _account("USER"); admin, _ = _account("ADMIN", remote=True); boss, _ = _account("SUPER_ADMIN")
    with TestClient(app) as client:
        headers = {"user": _auth(client, user), "admin": _auth(client, admin), "super": _auth(client, boss)}
        for route in SUPER_ROUTES:
            assert client.get(route).status_code == 401, route
            assert client.get(route, headers=headers["user"]).status_code == 403, route
            assert client.get(route, headers=headers["admin"]).status_code == 403, route
            assert client.get(route, headers=headers["super"]).status_code == 200, route
        assert "super.view" in client.get("/api/workspaces", headers=headers["super"]).json()["permissions"]
        assert "super.view" not in client.get("/api/workspaces", headers=headers["admin"]).json()["permissions"]


def test_admins_cannot_see_or_manage_super_admins_or_other_admins():
    admin, _ = _account("ADMIN", remote=True); other_admin, other_admin_id = _account("ADMIN", remote=True)
    boss, boss_id = _account("SUPER_ADMIN"); user, user_id = _account("USER")
    marker = uuid.uuid4().hex[:8]
    with TestClient(app) as client:
        a, s = _auth(client, admin), _auth(client, boss)
        listed_by_admin = {row["email"] for row in client.get("/api/users", headers=a).json()}
        assert boss not in listed_by_admin and other_admin in listed_by_admin and user in listed_by_admin
        assert boss in {row["email"] for row in client.get("/api/users", headers=s).json()}

        assert client.put(f"/api/users/{boss_id}", headers=a, json={"active": False}).status_code == 404
        assert client.put(f"/api/users/{other_admin_id}", headers=a, json={"remote_access": False}).status_code == 403
        assert client.put(f"/api/users/{user_id}", headers=a, json={"role": "ADMIN"}).status_code == 403
        for role in ("ADMIN", "SUPER_ADMIN"):
            body = {"email": f"new-{role.lower()}-{marker}@example.invalid", "name": "New account", "role": role, "password": PASSWORD}
            assert client.post("/api/users", headers=a, json=body).status_code == 403, role
        # Admins keep full control of user accounts.
        assert client.put(f"/api/users/{user_id}", headers=a, json={"remote_access": True}).json()["remote_access"] is True

        # The super admin manages admins and can create another super admin.
        assert client.put(f"/api/users/{other_admin_id}", headers=s, json={"remote_access": False}).json()["remote_access"] is False
        promoted = client.put(f"/api/users/{user_id}", headers=s, json={"role": "ADMIN"})
        assert promoted.status_code == 200 and promoted.json()["role"] == "ADMIN"
        created = client.post("/api/users", headers=s, json={"email": f"second-super-{marker}@example.invalid", "name": "Second super",
                                                             "role": "SUPER_ADMIN", "password": PASSWORD})
        assert created.status_code == 200 and created.json()["role"] == "SUPER_ADMIN"
        # Nobody can remove their own super admin role.
        demote_self = client.put(f"/api/users/{boss_id}", headers=s, json={"role": "ADMIN"})
        assert demote_self.status_code == 409
    db = SessionLocal()
    try:
        change = db.query(AuditLog).filter_by(action="CHANGE_ROLE", entity_id=str(user_id)).one()
        assert change.actor == boss and '"to": "ADMIN"' in change.detail_json
    finally:
        db.close()


def test_super_admin_decides_where_admins_may_work(behind_proxy):
    admin, admin_id = _account("ADMIN", remote=True); boss, _ = _account("SUPER_ADMIN", remote=False)
    with TestClient(app) as client:
        s = _auth(client, boss, OFFICE)
        assert client.put("/api/admin/network-access", headers=s, json={"enabled": True, "networks": [{"cidr": "52.14.20.0/24", "label": "Office"}]}).status_code == 200
        assert client.post("/api/auth/login", json={"email": admin, "password": PASSWORD}, headers={"X-Real-IP": ELSEWHERE}).status_code == 200

        assert client.put(f"/api/users/{admin_id}", headers=s, json={"remote_access": False}).status_code == 200
        blocked = client.post("/api/auth/login", json={"email": admin, "password": PASSWORD}, headers={"X-Real-IP": ELSEWHERE})
        assert blocked.status_code == 403 and "office network" in blocked.json()["detail"]
        assert client.post("/api/auth/login", json={"email": admin, "password": PASSWORD}, headers={"X-Real-IP": OFFICE}).status_code == 200
        # A super admin is never restricted, whatever its own switch says.
        assert client.post("/api/auth/login", json={"email": boss, "password": PASSWORD}, headers={"X-Real-IP": ELSEWHERE}).status_code == 200


def test_super_admin_lidar_urls_use_the_requested_api_host(monkeypatch):
    """A remote browser must not be sent to localhost on its own machine for local LiDAR."""
    monkeypatch.delenv("LIDAR_PUBLIC_BASE_URL", raising=False)
    boss, _ = _account("SUPER_ADMIN")
    project_id = f"sa-lidar-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        db.add(Project(id=project_id, name="Remote super admin LiDAR", customer="PLA", crs="EPSG:6424",
                       units="US survey foot", status="LIDAR_READY"))
        db.add(Pole(project_id=project_id, internal_id=1, pole_number="P-1", block_name="tile one"))
        db.add(LidarBlock(project_id=project_id, name="tile one", object_key=f"{project_id}/tile one.copc.laz",
                          x_min=0, y_min=0, x_max=1, y_max=1, point_count=10))
        db.commit()
    finally:
        db.close()

    with TestClient(app, base_url="http://remote-api.example:8123") as client:
        headers = _auth(client, boss)
        expected = f"http://remote-api.example:8123/api/storage/{project_id}/tile%20one.copc.laz"
        blocks = client.get(f"/api/projects/{project_id}/lidar-blocks", headers=headers)
        assert blocks.status_code == 200 and blocks.json()[0]["copc_url"] == expected
        scene = client.get(f"/api/projects/{project_id}/poles/1/scene", headers=headers)
        assert scene.status_code == 200 and scene.json()["blocks"][0]["copc_url"] == expected


def _production_dataset(super_email, user_email):
    """A Production dataset where a super admin completed pole 1 and a user completed pole 2."""
    project_id = f"sa-prod-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        db.add(Project(id=project_id, name="Super admin oversight", customer="PLA", crs="EPSG:6424", units="US survey foot", status="LIDAR_READY"))
        db.add(ProcessingJob(id=uuid.uuid4().hex, project_id=project_id, job_type="LIDAR_INGEST", payload_json="{}", status="SUCCEEDED"))
        for pole, author in ((1, super_email), (2, user_email)):
            db.add(Pole(project_id=project_id, internal_id=pole, pole_number=f"P-{pole}"))
            for feature, z in (("Pole_Base", 500.0), ("Pole_Top", 540.0)):
                db.add(ProductionAnnotation(id=uuid.uuid4().hex, project_id=project_id, block_name="tile", family="poles", feature_type=feature,
                                            x=0.0, y=0.0, z=z, pole_internal_id=pole, created_by=author, modified_by=author))
                db.add(AuditLog(actor=author, action="CREATE_PRODUCTION_ANNOTATION", entity_type="production_annotation", entity_id=uuid.uuid4().hex,
                                detail_json=f'{{"project_id": "{project_id}", "pole_internal_id": {pole}, "feature_type": "{feature}"}}'))
        db.commit()
    finally:
        db.close()
    return project_id


def test_super_admin_work_is_invisible_to_admins_and_users():
    user, _ = _account("USER"); admin, _ = _account("ADMIN", remote=True)
    boss, _ = _account("SUPER_ADMIN"); peer, _ = _account("SUPER_ADMIN")
    project_id = _production_dataset(boss, user)
    db = SessionLocal()
    try:
        viewer = {email: db.query(User).filter_by(email=email).one() for email in (user, admin, boss, peer)}
        assert boss in hidden_authors(db, viewer[user]) and admin in hidden_authors(db, viewer[user])
        assert boss in hidden_authors(db, viewer[admin]) and admin not in hidden_authors(db, viewer[admin])
        assert hidden_authors(db, viewer[peer]) == set(), "super admins see other super admins' work"
        assert _who(boss, viewer[admin], viewer) == "an admin" and _who(boss, viewer[peer], viewer) == viewer[boss].username
    finally:
        db.close()
    with TestClient(app) as client:
        as_admin = client.get(f"/api/projects/{project_id}/team-progress", headers=_auth(client, admin)).json()
        assert boss not in {row["email"] for row in as_admin["users"]} and user in {row["email"] for row in as_admin["users"]}
        assert as_admin["poles_completed"] == 1, "a hidden person's completed pole must not leak through the totals"
        as_peer = client.get(f"/api/projects/{project_id}/team-progress", headers=_auth(client, peer)).json()
        assert boss in {row["email"] for row in as_peer["users"]} and as_peer["poles_completed"] == 2

        everything = client.get("/api/super/team-progress?days=7", headers=_auth(client, peer)).json()
        assert everything["scope"] == "all" and project_id in {d["id"] for d in everything["datasets"]}
        assert next(row for row in everything["users"] if row["email"] == boss)["completed_total"] >= 1


def test_people_and_activity_feed():
    user, _ = _account("USER"); boss, _ = _account("SUPER_ADMIN")
    project_id = _production_dataset(boss, user)
    with TestClient(app) as client:
        s = _auth(client, boss)
        people = {row["email"]: row for row in client.get("/api/super/people?days=7", headers=s).json()}
        assert people[user]["points_period"] == 2 and people[user]["points_total"] == 2 and people[user]["poles_completed_total"] == 1
        assert people[boss]["role"] == "SUPER_ADMIN" and people[user]["last_active"]

        feed = client.get(f"/api/super/activity?project_id={project_id}&group=production&limit=3", headers=s).json()
        assert len(feed["items"]) == 3 and feed["next_before_id"]
        first = feed["items"][0]
        assert first["label"] == "Saved a point" and first["project_name"] == "Super admin oversight" and first["pole_internal_id"] in (1, 2)
        rest = client.get(f"/api/super/activity?project_id={project_id}&group=production&before_id={feed['next_before_id']}", headers=s).json()
        assert len(rest["items"]) == 1 and rest["next_before_id"] is None
        mine = client.get(f"/api/super/activity?actor={user}&project_id={project_id}", headers=s).json()["items"]
        assert {item["actor"] for item in mine} == {user} and len(mine) == 2
        assert client.get("/api/super/activity?group=bogus", headers=s).status_code == 422


def test_server_setting_promotes_the_first_super_admin(monkeypatch):
    email, user_id = _account("ADMIN", remote=True)
    db = SessionLocal()
    try:
        username = db.query(User.username).filter_by(id=user_id).scalar()
        monkeypatch.setenv("SUPER_ADMIN_EMAILS", f" {username.upper()} , nobody@example.invalid")
        assert promote_super_admins(db) == [username]
        db.expire_all()
        assert db.query(User.role).filter_by(id=user_id).scalar() == "SUPER_ADMIN"
        audit = db.query(AuditLog).filter_by(action="PROMOTE_SUPER_ADMIN", entity_id=str(user_id)).one()
        assert audit.actor == "system" and '"previous_role": "ADMIN"' in audit.detail_json
        assert promote_super_admins(db) == [], "already promoted: nothing changes"
        monkeypatch.delenv("SUPER_ADMIN_EMAILS")
        assert promote_super_admins(db) == []
    finally:
        db.close()


def test_upgrade_keeps_existing_admins_working_from_anywhere(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'upgrade.db'}")
    with engine.begin() as connection:
        command.upgrade(migration_config(connection), "20261007_0012")
        connection.execute(text("INSERT INTO users (email, name, role, password_hash, remote_access, created_at) VALUES "
                                "('a@example.invalid','A','ADMIN','x',0,'2026-10-01'), ('u@example.invalid','U','USER','x',0,'2026-10-01')"))
    initialize_schema(engine)
    with engine.connect() as connection:
        rows = dict(connection.execute(text("SELECT email, remote_access FROM users")).all())
    assert rows == {"a@example.invalid": 1, "u@example.invalid": 0}
