import os
from pathlib import Path
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
from app.db import Base, initialize_schema
from railway_entrypoint import validate_production_environment


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


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


def test_railway_image_isolates_and_validates_native_geospatial_libraries():
    dockerfile = (REPOSITORY_ROOT / 'Dockerfile').read_text(encoding='utf-8')

    assert 'mamba create --yes --name pla' in dockerfile
    assert 'mamba install --yes' not in dockerfile
    assert '/opt/conda/envs/pla/bin/pdal --drivers' in dockerfile
    assert 'PDAL_BIN=/opt/conda/envs/pla/bin/pdal' in dockerfile


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


def test_bucket_cors_derives_explicit_railway_origin(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.delenv('BUCKET_CORS_ORIGINS', raising=False)
    monkeypatch.delenv('CORS_ORIGINS', raising=False)
    monkeypatch.setenv('RAILWAY_PUBLIC_DOMAIN', 'qc.example.up.railway.app')

    assert storage.bucket_cors_origins() == ['https://qc.example.up.railway.app']


def test_bucket_cors_rejects_wildcard_in_strict_environment(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'staging')
    monkeypatch.setenv('BUCKET_CORS_ORIGINS', '*')

    with pytest.raises(RuntimeError, match='trusted origins'):
        storage.bucket_cors_origins()


def test_bucket_cors_requires_origin_in_strict_environment(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.delenv('BUCKET_CORS_ORIGINS', raising=False)
    monkeypatch.delenv('CORS_ORIGINS', raising=False)
    monkeypatch.delenv('RAILWAY_PUBLIC_DOMAIN', raising=False)

    with pytest.raises(RuntimeError, match='RAILWAY_PUBLIC_DOMAIN'):
        storage.bucket_cors_origins()


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


def test_staging_startup_uses_the_same_entrypoint_checks(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'staging')
    monkeypatch.setenv('DATABASE_URL', 'postgresql://example')
    monkeypatch.setenv('ADMIN_EMAIL', 'admin@example.com')
    monkeypatch.setenv('ADMIN_PASSWORD', 'a-unique-password')
    monkeypatch.setenv('JWT_SECRET', 'short')

    with pytest.raises(RuntimeError, match='JWT_SECRET'):
        validate_production_environment()


def test_preview_startup_skips_entrypoint_checks(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'preview')
    monkeypatch.delenv('JWT_SECRET', raising=False)
    validate_production_environment()


def test_schema_initializer_registers_v34_tables():
    initialize_schema()
    names = set(Base.metadata.tables)
    assert 'dataset_versions' in names
    assert 'processing_leases' in names
    assert 'correction_requests' in names


def test_railway_entrypoint_initializes_schema_before_children():
    source = (REPOSITORY_ROOT / 'api' / 'railway_entrypoint.py').read_text(encoding='utf-8')
    schema_pos = source.index('initialize_schema()')
    worker_pos = source.index('[sys.executable, "worker.py"]')
    assert schema_pos < worker_pos
