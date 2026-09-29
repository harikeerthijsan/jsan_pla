import os
from unittest.mock import Mock

import pytest

os.environ.setdefault('DATABASE_URL','sqlite:///./test_dynamic_api.db')
os.environ.setdefault('STORAGE_MODE','local')
os.environ.setdefault('LOCAL_STORAGE_ROOT','./test-storage')
os.environ.setdefault('JWT_SECRET','test-secret')
os.environ.setdefault('ADMIN_EMAIL','admin@jsan.local')
os.environ.setdefault('ADMIN_PASSWORD','ChangeMe123!')

from fastapi.testclient import TestClient

from app.main import app
from app import storage
from railway_entrypoint import validate_production_environment


def test_railway_image_serves_frontend_and_api_from_one_app():
    with TestClient(app) as client:
        root = client.get('/')
        health = client.get('/health')
        docs = client.get('/docs')

    assert root.status_code == 200
    assert 'PLA Quality Validation Workbench' in root.text
    assert health.status_code == 200
    assert health.json()['status'] == 'ok'
    assert docs.status_code == 200
    assert 'Swagger UI' in docs.text


def test_bucket_cors_supports_multipart_and_copc_reads(monkeypatch):
    client = Mock()
    monkeypatch.setattr(storage, 'MODE', 's3')
    monkeypatch.setattr(storage, '_s3', lambda: client)
    monkeypatch.setenv('AUTO_CONFIGURE_BUCKET_CORS', 'true')
    monkeypatch.setenv('BUCKET', 'test-bucket')
    monkeypatch.setenv(
        'BUCKET_CORS_ORIGINS',
        'https://one.example,https://two.example',
    )

    storage.configure_bucket_cors()

    args = client.put_bucket_cors.call_args.kwargs
    rule = args['CORSConfiguration']['CORSRules'][0]
    assert args['Bucket'] == 'test-bucket'
    assert rule['AllowedOrigins'] == [
        'https://one.example',
        'https://two.example',
    ]
    assert {'GET', 'HEAD', 'PUT', 'POST'} <= set(rule['AllowedMethods'])
    assert {'ETag', 'Content-Range'} <= set(rule['ExposeHeaders'])


def test_production_startup_rejects_incomplete_bucket_configuration(monkeypatch):
    variables = {
        'APP_ENV': 'production',
        'DATABASE_URL': 'postgresql://example',
        'ADMIN_EMAIL': 'admin@example.com',
        'ADMIN_PASSWORD': 'a-unique-password',
        'JWT_SECRET': 'x' * 32,
        'STORAGE_MODE': 's3',
        'BUCKET': 'test-bucket',
        'BUCKET_ACCESS_KEY_ID': 'access-key',
        'BUCKET_SECRET_ACCESS_KEY': 'secret-key',
    }
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    for name in ('BUCKET_ENDPOINT', 'S3_ENDPOINT_URL', 'AWS_ENDPOINT_URL', 'ENDPOINT'):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match='bucket endpoint'):
        validate_production_environment()
