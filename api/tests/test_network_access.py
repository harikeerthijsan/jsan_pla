"""Users can be limited to office networks; admins and users with remote access are exempt."""
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

from app.auth import hash_password
from app.db import SessionLocal, initialize_schema
from app.main import app
from app.models import AppSetting, AuditLog, User
from app.network_access import POLICY_KEY

PASSWORD = "Network-Test-Password-1!"
OFFICE = "52.14.20.7"       # stands in for the office's public internet address
ELSEWHERE = "34.120.5.9"


@pytest.fixture
def behind_proxy(monkeypatch):
    """Simulate Railway: the trusted client address comes from X-Real-IP. The policy is always reset afterwards."""
    monkeypatch.setenv("CLIENT_IP_HEADER", "X-Real-IP")
    initialize_schema()
    yield
    db = SessionLocal()
    try:
        db.query(AppSetting).filter_by(key=POLICY_KEY).delete()
        db.commit()
    finally:
        db.close()


def _user(role="USER"):
    marker = uuid.uuid4().hex[:8]
    email = f"net-{role.lower()}-{marker}@example.invalid"
    db = SessionLocal()
    try:
        db.add(User(email=email, username=f"N{marker}", name=f"Net {marker}", role=role, password_hash=hash_password(PASSWORD)))
        db.commit()
        return email, db.query(User.id).filter_by(email=email).scalar()
    finally:
        db.close()


def _login(client, email, ip, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password}, headers={"X-Real-IP": ip})


def _auth(client, email, ip, password=PASSWORD):
    response = _login(client, email, ip, password)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}", "X-Real-IP": ip}


def test_policy_endpoints_require_an_admin_and_validate_networks(behind_proxy):
    user_email, _ = _user()
    with TestClient(app) as client:
        admin = _auth(client, "admin@jsan.local", OFFICE, "ChangeMe123!")
        user = _auth(client, user_email, OFFICE)
        assert client.get("/api/admin/network-access").status_code == 401
        assert client.get("/api/admin/network-access", headers=user).status_code == 403
        assert client.put("/api/admin/network-access", headers=user, json={"enabled": False, "networks": []}).status_code == 403

        view = client.get("/api/admin/network-access", headers=admin).json()
        assert view["enabled"] is False and view["your_ip"] == OFFICE and view["your_ip_listed"] is False

        assert client.put("/api/admin/network-access", headers=admin, json={"enabled": True, "networks": []}).status_code == 422
        bad = client.put("/api/admin/network-access", headers=admin, json={"enabled": False, "networks": [{"cidr": "office", "label": ""}]})
        assert bad.status_code == 422 and "not an IP" in bad.json()["detail"]
        # Behind Railway a LAN address can never match: explain instead of saving a useless rule.
        lan = client.put("/api/admin/network-access", headers=admin, json={"enabled": True, "networks": [{"cidr": "192.168.3.100", "label": "LAN"}]})
        assert lan.status_code == 422 and "private office" in lan.json()["detail"]

        saved = client.put("/api/admin/network-access", headers=admin, json={"enabled": True, "networks": [
            {"cidr": OFFICE, "label": "Head office"}, {"cidr": "52.14.20.7/32", "label": "duplicate"}]})
        assert saved.status_code == 200
        assert saved.json()["networks"] == [{"cidr": "52.14.20.7/32", "label": "Head office"}] and saved.json()["your_ip_listed"] is True
        db = SessionLocal()
        try:
            assert db.query(AuditLog).filter_by(action="UPDATE_NETWORK_POLICY").order_by(AuditLog.id.desc()).first().actor == "admin@jsan.local"
        finally:
            db.close()


def test_users_work_only_from_listed_networks_admins_from_anywhere(behind_proxy):
    user_email, _ = _user()
    with TestClient(app) as client:
        admin = _auth(client, "admin@jsan.local", OFFICE, "ChangeMe123!")
        user_in_office = _auth(client, user_email, OFFICE)
        client.put("/api/admin/network-access", headers=admin, json={"enabled": True, "networks": [{"cidr": "52.14.20.0/24", "label": "Office"}]})

        assert client.get("/api/projects", headers=user_in_office).status_code == 200
        blocked = _login(client, user_email, ELSEWHERE)
        assert blocked.status_code == 403 and "office network" in blocked.json()["detail"]
        # A token taken from the office stops working off-network.
        moved = client.get("/api/projects", headers={**user_in_office, "X-Real-IP": ELSEWHERE})
        assert moved.status_code == 403 and moved.json()["detail"] == "network_not_allowed"
        # A request without the trusted proxy header is not trusted.
        assert client.get("/api/projects", headers={"Authorization": user_in_office["Authorization"]}).status_code == 403
        # Admins are never restricted.
        assert _login(client, "admin@jsan.local", ELSEWHERE, "ChangeMe123!").status_code == 200

        db = SessionLocal()
        try:
            assert db.query(AuditLog).filter_by(action="LOGIN_BLOCKED_NETWORK").order_by(AuditLog.id.desc()).first().detail_json == f'{{"ip": "{ELSEWHERE}"}}'
        finally:
            db.close()

        # Turning the restriction off restores access immediately.
        client.put("/api/admin/network-access", headers=admin, json={"enabled": False, "networks": [{"cidr": "52.14.20.0/24", "label": "Office"}]})
        assert _login(client, user_email, ELSEWHERE).status_code == 200


def test_admin_can_give_a_user_access_from_anywhere(behind_proxy):
    user_email, user_id = _user()
    other_email, _ = _user()
    with TestClient(app) as client:
        admin = _auth(client, "admin@jsan.local", OFFICE, "ChangeMe123!")
        other = _auth(client, other_email, OFFICE)
        client.put("/api/admin/network-access", headers=admin, json={"enabled": True, "networks": [{"cidr": OFFICE, "label": "Office"}]})
        assert _login(client, user_email, ELSEWHERE).status_code == 403

        # Only admins grant it.
        assert client.put(f"/api/users/{user_id}", headers=other, json={"remote_access": True}).status_code == 403
        granted = client.put(f"/api/users/{user_id}", headers=admin, json={"remote_access": True})
        assert granted.status_code == 200 and granted.json()["remote_access"] is True
        assert _login(client, user_email, ELSEWHERE).status_code == 200
        assert client.get("/api/admin/network-access", headers=admin).json()["users_with_remote_access"] >= 1

        revoked = client.put(f"/api/users/{user_id}", headers=admin, json={"remote_access": False})
        assert revoked.json()["remote_access"] is False
        assert _login(client, user_email, ELSEWHERE).status_code == 403
        db = SessionLocal()
        try:
            actions = [row.action for row in db.query(AuditLog).filter_by(entity_id=str(user_id)).all()]
            assert "ALLOW_REMOTE_ACCESS" in actions and "REVOKE_REMOTE_ACCESS" in actions
        finally:
            db.close()


def test_without_a_proxy_header_setting_the_socket_address_is_used(monkeypatch):
    # Local development: no trusted header, so a client-supplied X-Real-IP is ignored.
    monkeypatch.delenv("CLIENT_IP_HEADER", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    from starlette.requests import Request

    from app.network_access import client_ip
    request = Request({"type": "http", "headers": [(b"x-real-ip", OFFICE.encode())], "client": ("127.0.0.1", 5000)})
    assert client_ip(request) == "127.0.0.1"
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    assert client_ip(request) == OFFICE
