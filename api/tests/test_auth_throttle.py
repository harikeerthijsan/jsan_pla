"""Sign-in throttles live in the database, so several API processes / replicas enforce one shared limit."""
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
from app.main import LOGIN_MAX_FAILURES, app
from app.models import AuthThrottleEvent, User


def make_user():
    initialize_schema()
    email = f"throttle-{uuid.uuid4().hex[:8]}@example.invalid"
    db = SessionLocal()
    try:
        db.add(User(email=email, name="Throttle test", role="USER", password_hash=hash_password("Unique-Test-Password-123!"))); db.commit()
    finally:
        db.close()
    return email


def test_failed_logins_lock_out_across_processes_and_success_clears():
    throttle.clear()
    email = make_user()
    with TestClient(app) as first:
        for _ in range(LOGIN_MAX_FAILURES):
            assert first.post("/api/auth/login", json={"email": email, "password": "wrong-password-123"}).status_code == 401
        assert first.post("/api/auth/login", json={"email": email, "password": "wrong-password-123"}).status_code == 429
    # A different process sees the same count: it is stored in the database, not in memory.
    db = SessionLocal()
    try:
        assert db.query(AuthThrottleEvent).filter(AuthThrottleEvent.key.like(f"login|%|{email}")).count() == LOGIN_MAX_FAILURES
    finally:
        db.close()
    with TestClient(app) as second:
        assert second.post("/api/auth/login", json={"email": email, "password": "Unique-Test-Password-123!"}).status_code == 429
    # After the window (simulated by clearing), the right password works and leaves no count behind.
    throttle.clear()
    with TestClient(app) as client:
        assert client.post("/api/auth/login", json={"email": email, "password": "wrong-password-123"}).status_code == 401
        assert client.post("/api/auth/login", json={"email": email, "password": "Unique-Test-Password-123!"}).status_code == 200
    assert throttle.hits(f"login|testclient|{email}", 3600) == 0


def test_check_and_record_counts_inside_the_window():
    throttle.clear()
    key = f"unit|{uuid.uuid4().hex}"
    assert [throttle.check_and_record(key, 2, 60) for _ in range(3)] == [False, False, True]
    assert throttle.hits(key, 60) == 2 and throttle.hits(key, 0) == 0
