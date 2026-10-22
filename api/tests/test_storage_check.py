"""Super-admin storage check: tests this service's bucket credentials without revealing them."""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_dynamic_api.db")
os.environ.setdefault("STORAGE_MODE", "local")
os.environ.setdefault("LOCAL_STORAGE_ROOT", "./test-storage")
os.environ.setdefault("JWT_SECRET", "test-secret")

from fastapi.testclient import TestClient

from app import storage
from app.auth import hash_password
from app.db import SessionLocal
from app.main import app


class FakeS3:
    def head_bucket(self, Bucket):
        return {}

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return "https://bucket.example/obj"


def test_storage_check_requires_super_admin_and_reveals_no_secret(monkeypatch):
    from app.models import User
    email = f"storage-admin-{uuid.uuid4().hex[:6]}@example.invalid"
    super_email = f"storage-super-{uuid.uuid4().hex[:6]}@example.invalid"
    db = SessionLocal()
    try:
        db.add(User(email=email, name="Admin", role="ADMIN", password_hash=hash_password("Unique-Test-Password-123!")))
        db.add(User(email=super_email, name="Super", role="SUPER_ADMIN", password_hash=hash_password("Unique-Test-Password-123!"))); db.commit()
    finally:
        db.close()
    with TestClient(app) as client:
        assert client.get("/api/admin/storage-check").status_code == 401
        admin = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": email, "password": "Unique-Test-Password-123!"}).json()["token"]}
        assert client.get("/api/admin/storage-check", headers=admin).status_code == 403
        sup = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": super_email, "password": "Unique-Test-Password-123!"}).json()["token"]}
        assert client.get("/api/admin/storage-check", headers=sup).json()["mode"] == "local"   # super admin, local mode

    monkeypatch.setattr(storage, "MODE", "s3")
    monkeypatch.setattr(storage, "_s3", lambda: FakeS3())
    monkeypatch.setenv("BUCKET", "bucket")
    monkeypatch.setenv("BUCKET_ACCESS_KEY_ID", "tid_ABCDEFGHIJ")
    monkeypatch.setenv("BUCKET_SECRET_ACCESS_KEY", "secret-value-with-space ")

    import urllib.error, io
    def reject(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b"<Error><Code>SignatureDoesNotMatch</Code></Error>"))
    monkeypatch.setattr("urllib.request.urlopen", reject)
    result = storage.storage_diagnostics("p/tile.copc.laz")
    assert result["checks"] == {"bucket": "ok", "presigned_get": "failed: HTTP 403 SignatureDoesNotMatch"}
    assert result["access_key_id_starts"] == "tid_AB…" and result["secret_has_whitespace_or_quotes"] is True
    assert "secret-value" not in str(result)
