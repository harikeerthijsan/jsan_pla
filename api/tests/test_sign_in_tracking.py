"""Admins see each account's last sign-in time and (when shared) the browser location; only the latest is kept."""
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
from app.models import User

PASSWORD = "Sign-In-Test-Password-1!"
HYDERABAD = {"latitude": 17.4401, "longitude": 78.3489, "accuracy": 25.0}


def _user():
    initialize_schema()
    email = f"signin-{uuid.uuid4().hex[:8]}@example.invalid"
    db = SessionLocal()
    try:
        db.add(User(email=email, username=email.split("@")[0], name="Sign-in test", role="USER", password_hash=hash_password(PASSWORD)))
        db.commit()
    finally:
        db.close()
    return email


def _login(client, email, password=PASSWORD):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}, response.json()["user"]


def _row(client, admin, email):
    return next(row for row in client.get("/api/users", headers=admin).json() if row["email"] == email)


def test_sign_in_records_time_and_address_then_the_shared_location():
    email = _user()
    with TestClient(app) as client:
        assert client.post("/api/auth/sign-in-location", json={"status": "shared", **HYDERABAD}).status_code == 401
        user, account = _login(client, email)
        assert account["last_login_at"] and account["last_login_location"]["status"] == "pending"

        shared = client.post("/api/auth/sign-in-location", headers=user, json={"status": "shared", **HYDERABAD})
        assert shared.status_code == 200 and shared.json()["last_login_location"]["latitude"] == HYDERABAD["latitude"]
        # The person sees their own record; only admins see everyone's.
        assert client.get("/api/auth/me", headers=user).json()["last_login_location"]["status"] == "shared"
        assert client.get("/api/users", headers=user).status_code == 403
        admin, _ = _login(client, "admin@jsan.local", "ChangeMe123!")
        row = _row(client, admin, email)
        # TestClient has no real address, so none is recorded; on Railway this is the X-Real-IP address.
        assert "last_login_ip" in row and row["last_login_at"]
        assert row["last_login_location"] == {**row["last_login_location"], "status": "shared", "latitude": 17.4401, "longitude": 78.3489, "accuracy": 25.0}

        # A new sign-in replaces the old record (no history of places is kept).
        user, account = _login(client, email)
        assert account["last_login_location"]["status"] == "pending" and account["last_login_location"]["latitude"] is None
        denied = client.post("/api/auth/sign-in-location", headers=user, json={"status": "denied"})
        assert denied.status_code == 200 and denied.json()["last_login_location"] == {**denied.json()["last_login_location"], "status": "denied", "latitude": None}


def test_location_is_validated_and_only_accepted_right_after_sign_in():
    email = _user()
    with TestClient(app) as client:
        user, _ = _login(client, email)
        assert client.post("/api/auth/sign-in-location", headers=user, json={"status": "shared"}).status_code == 422
        assert client.post("/api/auth/sign-in-location", headers=user, json={"status": "shared", "latitude": 95, "longitude": 10}).status_code == 422
        assert client.post("/api/auth/sign-in-location", headers=user, json={"status": "somewhere"}).status_code == 422
        db = SessionLocal()
        try:
            row = db.query(User).filter_by(email=email).one()
            row.last_login_at = datetime.now(timezone.utc) - timedelta(minutes=30)
            db.commit()
        finally:
            db.close()
        late = client.post("/api/auth/sign-in-location", headers=user, json={"status": "shared", **HYDERABAD})
        assert late.status_code == 409


def test_location_can_be_reported_before_a_forced_password_change():
    email = _user()
    db = SessionLocal()
    try:
        db.query(User).filter_by(email=email).one().must_change_password = True
        db.commit()
    finally:
        db.close()
    with TestClient(app) as client:
        user, _ = _login(client, email)
        assert client.post("/api/auth/sign-in-location", headers=user, json={"status": "shared", **HYDERABAD}).status_code == 200


def test_pages_may_request_location_but_not_camera_or_microphone():
    # A geolocation=() policy would silently block the sign-in location prompt for everyone.
    with TestClient(app) as client:
        policy = client.get("/health").headers["permissions-policy"]
    assert "geolocation=(self)" in policy and "camera=()" in policy and "microphone=()" in policy
