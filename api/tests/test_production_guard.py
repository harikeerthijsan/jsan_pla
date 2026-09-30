import pytest
import app.main as main


SAFE_ENV = {
    'DATABASE_URL': 'postgresql+psycopg://user:pass@postgres.railway.internal:5432/railway',
    'JWT_SECRET': 'x' * 48,
    'ADMIN_PASSWORD': 'A-long-unique-bootstrap-password',
    'CORS_ORIGINS': 'https://qc.example.com',
    'SEED_DEMO': 'false',
}


@pytest.fixture(autouse=True)
def _no_railway_identity(monkeypatch):
    for name in ('RAILWAY_ENVIRONMENT_NAME', 'PRODUCTION_RAILWAY_ENVIRONMENT'):
        monkeypatch.delenv(name, raising=False)


def _strict(monkeypatch, app_env, **overrides):
    monkeypatch.setattr(main, 'APP_ENV', app_env)
    monkeypatch.setattr(main, 'MODE', 's3')
    for name, value in {**SAFE_ENV, **overrides}.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def test_development_guard_allows_local(monkeypatch):
    monkeypatch.setattr(main, 'APP_ENV', 'development')
    main.validate_runtime_environment()


def test_preview_is_not_held_to_production_guard(monkeypatch):
    monkeypatch.setattr(main, 'APP_ENV', 'preview')
    monkeypatch.setattr(main, 'MODE', 'local')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///./x.db')
    main.validate_runtime_environment()


def test_production_guard_rejects_unsafe_defaults(monkeypatch):
    monkeypatch.setattr(main, 'APP_ENV', 'production')
    monkeypatch.setattr(main, 'MODE', 'local')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///./x.db')
    monkeypatch.setenv('JWT_SECRET', 'dev-only-change-me')
    monkeypatch.setenv('ADMIN_PASSWORD', 'ChangeMe123!')
    monkeypatch.setenv('CORS_ORIGINS', '*')
    monkeypatch.setenv('SEED_DEMO', 'true')
    with pytest.raises(RuntimeError) as exc:
        main.validate_runtime_environment()
    msg=str(exc.value)
    assert 'PostgreSQL' in msg
    assert 'JWT_SECRET' in msg
    assert 'STORAGE_MODE' in msg
    assert 'CORS_ORIGINS' in msg
    assert 'ADMIN_PASSWORD' in msg
    assert 'SEED_DEMO' in msg


def test_production_guard_accepts_safe_shape(monkeypatch):
    _strict(monkeypatch, 'production')
    main.validate_runtime_environment()


def test_production_guard_accepts_same_origin_without_cors_allowlist(monkeypatch):
    # The live Railway service serves UI and API from one origin and does not set CORS_ORIGINS.
    _strict(monkeypatch, 'production', CORS_ORIGINS=None)
    main.validate_runtime_environment()


@pytest.mark.parametrize('overrides,fragment', [
    ({'DATABASE_URL': None}, 'PostgreSQL'),
    ({'JWT_SECRET': 'short'}, 'JWT_SECRET'),
    ({'JWT_SECRET': None}, 'JWT_SECRET'),
    ({'ADMIN_PASSWORD': 'short'}, 'ADMIN_PASSWORD'),
    ({'ADMIN_PASSWORD': None}, 'ADMIN_PASSWORD'),
    ({'CORS_ORIGINS': 'https://qc.example.com, *'}, 'CORS_ORIGINS'),
    ({'SEED_DEMO': 'TRUE'}, 'SEED_DEMO'),
])
def test_staging_is_guarded_like_production(monkeypatch, overrides, fragment):
    _strict(monkeypatch, 'staging', **overrides)
    with pytest.raises(RuntimeError, match=fragment):
        main.validate_runtime_environment()


def test_staging_rejects_local_storage(monkeypatch):
    _strict(monkeypatch, 'staging')
    monkeypatch.setattr(main, 'MODE', 'local')
    with pytest.raises(RuntimeError, match='STORAGE_MODE'):
        main.validate_runtime_environment()


def test_environment_duplicated_from_production_cannot_claim_production(monkeypatch):
    # A Railway staging/PR environment copied from production still carries APP_ENV=production.
    _strict(monkeypatch, 'production', RAILWAY_ENVIRONMENT_NAME='staging')
    with pytest.raises(RuntimeError, match="Railway environment is 'staging'"):
        main.validate_runtime_environment()


def test_production_railway_environment_requires_production_app_env(monkeypatch):
    _strict(monkeypatch, 'staging', RAILWAY_ENVIRONMENT_NAME='production')
    with pytest.raises(RuntimeError, match="is production but APP_ENV=staging"):
        main.validate_runtime_environment()


def test_matching_railway_environment_is_accepted(monkeypatch):
    _strict(monkeypatch, 'production', RAILWAY_ENVIRONMENT_NAME='production')
    main.validate_runtime_environment()
    _strict(monkeypatch, 'staging', RAILWAY_ENVIRONMENT_NAME='staging')
    main.validate_runtime_environment()


def test_production_environment_name_is_configurable(monkeypatch):
    _strict(monkeypatch, 'production', RAILWAY_ENVIRONMENT_NAME='prod', PRODUCTION_RAILWAY_ENVIRONMENT='prod')
    main.validate_runtime_environment()


def test_guard_runs_before_application_startup(monkeypatch):
    from fastapi.testclient import TestClient
    _strict(monkeypatch, 'production', JWT_SECRET='short')
    with pytest.raises(RuntimeError, match='JWT_SECRET'):
        with TestClient(main.app):
            pass
