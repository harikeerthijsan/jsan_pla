"""LiDAR (COPC) range responses must not be stored by the browser: Chrome's cache can fail to combine cached and new
ranges (net::ERR_CACHE_OPERATION_NOT_SUPPORTED), which breaks LiDAR loading on the deployed site."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_dynamic_api.db")
os.environ.setdefault("STORAGE_MODE", "local")
os.environ.setdefault("LOCAL_STORAGE_ROOT", "./test-storage")
os.environ.setdefault("JWT_SECRET", "test-secret")

from fastapi.testclient import TestClient

from app import storage
from app.main import app


class FakeS3:
    def __init__(self):
        self.calls = []

    def generate_presigned_url(self, operation, Params, ExpiresIn, **kwargs):
        self.calls.append((operation, dict(Params)))
        return "https://bucket.example/signed"


def test_signed_lidar_links_ask_the_browser_not_to_store(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(storage, "MODE", "s3")
    monkeypatch.setattr(storage, "_s3", lambda: fake)
    monkeypatch.setattr(storage, "bucket_name", lambda: "bucket")
    assert storage.block_url("p/versions/v1/lidar/tile.copc.laz") == "https://bucket.example/signed"
    assert fake.calls[-1] == ("get_object", {"Bucket": "bucket", "Key": "p/versions/v1/lidar/tile.copc.laz", "ResponseCacheControl": "no-store"})
    # Can be switched off if a storage provider rejects the override.
    monkeypatch.setattr(storage, "LIDAR_CACHE_CONTROL", "")
    storage.block_url("p/tile.copc.laz")
    assert "ResponseCacheControl" not in fake.calls[-1][1]


def test_locally_served_lidar_is_not_stored_either():
    key = "cache-header-test/versions/v1/lidar/tile.copc.laz"
    path = storage.local_path(key); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"LASF" + b"\0" * 2000)
    with TestClient(app) as client:
        whole = client.get(f"/api/storage/{key}")
        part = client.get(f"/api/storage/{key}", headers={"Range": "bytes=0-99"})
    assert whole.status_code == 200 and whole.headers["cache-control"] == "no-store"
    assert part.status_code == 206 and len(part.content) == 100 and part.headers["cache-control"] == "no-store"
