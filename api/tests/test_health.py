import os
os.environ.setdefault('DATABASE_URL','sqlite:///./test_dynamic_api.db')
os.environ.setdefault('STORAGE_MODE','local')
os.environ.setdefault('LOCAL_STORAGE_ROOT','./test-storage')
os.environ.setdefault('JWT_SECRET','test-secret')
os.environ.setdefault('ADMIN_EMAIL','admin@jsan.local')
os.environ.setdefault('ADMIN_PASSWORD','ChangeMe123!')

from fastapi.testclient import TestClient

import app.main as main


class _BrokenEngine:
    def connect(self):
        raise RuntimeError('connection to postgres://user:pw@db.internal failed')


def test_live_needs_no_dependencies():
    with TestClient(main.app) as client:
        r = client.get('/health/live')
    assert r.status_code == 200
    assert r.json()['status'] == 'live'
    assert r.json()['app_env'] == main.APP_ENV


def test_ready_checks_database_and_storage():
    with TestClient(main.app) as client:
        r = client.get('/health/ready')
    assert r.status_code == 200
    body = r.json()
    assert body['status'] == 'ready'
    assert body['checks'] == {'database': 'ok', 'storage': 'ok'}


def test_ready_returns_503_without_leaking_database_errors(monkeypatch):
    with TestClient(main.app) as client:
        monkeypatch.setattr(main, 'engine', _BrokenEngine())
        r = client.get('/health/ready')
    assert r.status_code == 503
    assert r.json()['checks']['database'] == 'fail'
    assert 'pw@' not in r.text and 'db.internal' not in r.text


def test_ready_fails_when_s3_bucket_is_not_configured(monkeypatch):
    with TestClient(main.app) as client:
        monkeypatch.setattr(main, 'MODE', 's3')
        monkeypatch.setattr(main, 'bucket_name', lambda: None)
        r = client.get('/health/ready')
    assert r.status_code == 503
    assert r.json()['checks']['storage'] == 'fail'


def test_legacy_health_contract_unchanged():
    with TestClient(main.app) as client:
        r = client.get('/health')
    assert r.status_code == 200
    assert r.json()['status'] == 'ok'
