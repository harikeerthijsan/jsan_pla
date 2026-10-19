"""Self-registration: an email in the employee directory, without an account, becomes a User account."""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_dynamic_api.db")
os.environ.setdefault("STORAGE_MODE", "local")
os.environ.setdefault("LOCAL_STORAGE_ROOT", "./test-storage")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@jsan.local")
os.environ.setdefault("ADMIN_PASSWORD", "ChangeMe123!")

from fastapi.testclient import TestClient

from app import throttle
from app.auth import hash_password
from app.db import SessionLocal, initialize_schema
from app.main import app
from app.models import AuditLog, EmployeeRecord, User

PASSWORD = "Registered-Pass-2026!"


def employee(with_account=False):
    initialize_schema()
    marker = uuid.uuid4().hex[:8]
    email = f"reg-{marker}@example.invalid"
    db = SessionLocal()
    try:
        row = EmployeeRecord(name=f"Registrant {marker}", jsan_id=f"JR{marker}", email=email)
        if with_account:
            user = User(email=email, username=f"has{marker}", name="Has account", role="USER", password_hash=hash_password(PASSWORD))
            db.add(user); db.flush(); row.user_id = user.id
        db.add(row); db.commit()
        return email, row.jsan_id
    finally:
        db.close()


def test_check_finds_directory_emails_without_an_account():
    throttle.clear()
    email, jsan_id = employee()
    with TestClient(app) as client:
        found = client.post("/api/auth/register/check", json={"email": email.upper()})
        assert found.status_code == 200 and found.json()["jsan_id"] == jsan_id and found.json()["suggested_username"] == jsan_id
        assert client.post("/api/auth/register/check", json={"email": "nobody-here@example.invalid"}).status_code == 404
        taken, _ = employee(with_account=True)
        assert client.post("/api/auth/register/check", json={"email": taken}).status_code == 409
        # An account that exists but is not linked to the directory row also blocks registration (no takeover).
        assert client.post("/api/auth/register/check", json={"email": "admin@jsan.local"}).status_code in (404, 409)


def test_register_creates_a_linked_user_account_that_can_sign_in():
    throttle.clear()
    email, jsan_id = employee()
    with TestClient(app) as client:
        # Weak passwords are refused: too short, or the same as the username.
        assert client.post("/api/auth/register", json={"email": email, "username": jsan_id, "password": "short"}).status_code == 422
        assert client.post("/api/auth/register", json={"email": email, "username": "samepassword12", "password": "samepassword12"}).status_code == 422
        done = client.post("/api/auth/register", json={"email": email, "username": jsan_id, "password": PASSWORD, "role": "SUPER_ADMIN"})
        assert done.status_code == 200, done.text
        assert done.json()["username"] == jsan_id
        # Registering again, or taking the username, is refused.
        assert client.post("/api/auth/register", json={"email": email, "username": "other", "password": PASSWORD}).status_code == 409
        login = client.post("/api/auth/login", json={"email": jsan_id, "password": PASSWORD})
        assert login.status_code == 200 and login.json()["user"]["role"] == "USER"
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=email).one()
        assert user.role == "USER" and user.is_active and not user.must_change_password and not user.remote_access
        row = db.query(EmployeeRecord).filter_by(email=email).one()
        assert row.user_id == user.id                      # the super admin directory now shows access
        assert db.query(AuditLog).filter_by(action="SELF_REGISTER", entity_id=str(user.id)).count() == 1
    finally:
        db.close()


def test_username_must_be_free_and_valid():
    throttle.clear()
    email, _ = employee()
    other_email, other_jsan = employee()
    with TestClient(app) as client:
        assert client.post("/api/auth/register", json={"email": other_email, "username": other_jsan, "password": PASSWORD}).status_code == 200
        assert client.post("/api/auth/register", json={"email": email, "username": other_jsan, "password": PASSWORD}).status_code == 409
        assert client.post("/api/auth/register", json={"email": email, "username": "has space", "password": PASSWORD}).status_code == 422


def test_registration_is_throttled():
    throttle.clear()
    with TestClient(app) as client:
        codes = [client.post("/api/auth/register/check", json={"email": "throttle-probe@example.invalid"}).status_code for _ in range(12)]
    assert codes[:10] == [404] * 10 and codes[-1] == 429
    throttle.clear()


def test_an_address_used_as_another_accounts_sign_in_email_cannot_register():
    throttle.clear()
    email, _ = employee()
    db = SessionLocal()
    try:
        marker = uuid.uuid4().hex[:8]
        db.add(User(email=f"other-{marker}@example.invalid", username=f"other{marker}", name="Existing person", role="ADMIN",
                    password_hash=hash_password(PASSWORD), sign_in_email=email.upper()))
        db.commit()
    finally:
        db.close()
    with TestClient(app) as client:
        assert client.post("/api/auth/register/check", json={"email": email}).status_code == 409
        assert client.post("/api/auth/register", json={"email": email, "username": f"new{uuid.uuid4().hex[:6]}", "password": PASSWORD}).status_code == 409
