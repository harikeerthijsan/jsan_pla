"""Pin the CI / Railway release contract so it cannot silently drift (Task 04)."""

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def read(relative):
    return (ROOT / relative).read_text(encoding='utf-8')


def test_release_identity_is_consistent():
    version = read('VERSION.txt').strip()
    assert version == '3.4.1-operational'
    assert f'APP_VERSION={version}' in read('Dockerfile')
    assert f'APP_VERSION: "{version}"' in read('.railway/railway.ts')
    assert f"'{version}'" in read('api/app/main.py')


def test_railway_healthcheck_uses_readiness_endpoint():
    railway = read('.railway/railway.ts')
    assert 'healthcheck: "/health/ready"' in railway
    assert 'healthcheck: "/health"' not in railway


def test_railway_app_env_follows_environment_not_hard_coded_production():
    railway = read('.railway/railway.ts')
    assert 'APP_ENV: "production"' not in railway
    assert 'APP_ENV: appEnvFor(ctx.environment)' in railway
    assert 'SEED_DEMO: "false"' in railway
    assert 'STORAGE_MODE: "s3"' in railway


def test_railway_resources_use_per_environment_reference_variables():
    railway = read('.railway/railway.ts')
    # Literal credentials would be shared across environments; references resolve per environment.
    assert 'DATABASE_URL: database.env.DATABASE_URL' in railway
    for key in ('BUCKET', 'ACCESS_KEY_ID', 'SECRET_ACCESS_KEY', 'ENDPOINT'):
        assert '${{pla-files.' + key + '}}' in railway


def test_railway_bucket_cors_is_not_wildcarded():
    railway = read('.railway/railway.ts')
    assert 'BUCKET_CORS_ORIGINS: "*"' not in railway


def test_ci_gates_pull_requests_and_deploy_branches():
    ci = read('.github/workflows/ci.yml')
    assert re.search(r'^\s*pull_request:\s*$', ci, re.MULTILINE)
    assert 'branches: [main, staging]' in ci
    assert 'python -m pip check' in ci
    assert 'python -m compileall' in ci
    assert 'python -m pytest -q' in ci
    assert 'node --check web/assets/app.js' in ci
    assert 'scripts/check_repo_hygiene.py' in ci or 'scripts/ci/check_repo_hygiene.py' in ci


def test_ci_builds_the_images_railway_deploys_on_every_pull_request():
    ci = read('.github/workflows/ci.yml')
    assert 'file: ./Dockerfile' in ci
    assert 'file: ./worker/Dockerfile' in ci
    # Image jobs must not be restricted to main/staging; PRs need them too.
    assert 'if: github.ref' not in ci
    assert '/health/ready' in ci
    assert 'Unsafe production configuration' in ci


def test_ci_reviews_dependencies_and_scans_built_images():
    ci = read('.github/workflows/ci.yml')
    assert 'actions/dependency-review-action@v4' in ci
    assert ci.count('aquasecurity/trivy-action@v0.36.0') == 2
    assert ci.count("severity: HIGH,CRITICAL") == 2
    assert ci.count("exit-code: '0'") == 2
    assert ci.count('scripts/ci/check_trivy_report.py') == 2


def test_workflows_use_no_secrets_or_privileged_triggers():
    for workflow in (ROOT / '.github' / 'workflows').glob('*.yml'):
        text = workflow.read_text(encoding='utf-8')
        assert 'secrets.' not in text, workflow.name
        assert 'pull_request_target' not in text, workflow.name
        assert 'permissions:\n  contents: read' in text, workflow.name


def test_ci_never_cancels_deploy_branch_runs():
    ci = read('.github/workflows/ci.yml')
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in ci


def test_deployed_images_keep_pinned_native_geospatial_stack():
    for dockerfile in ('Dockerfile', 'worker/Dockerfile'):
        text = read(dockerfile)
        assert 'FROM condaforge/miniforge3:26.7.2-0 AS geospatial' in text, dockerfile
        assert 'FROM ubuntu:24.04' in text, dockerfile
        assert 'COPY --from=geospatial /opt/conda/envs/pla /opt/conda/envs/pla' in text, dockerfile
        assert '"pdal=2.10.2" "gdal=3.13.3" "libsqlite>=3.51.0,<4"' in text, dockerfile
        assert '"setuptools>=78.1.1" "msgpack-python>=1.2.1"' in text, dockerfile
        assert '--upgrade --force-reinstall' in text, dockerfile
        assert "setuptools.__version__.split('.')[:3]" in text, dockerfile
        assert 'assert msgpack.version >= (1, 2, 1)' in text, dockerfile
        assert 'conda-meta/setuptools-*.json' in text, dockerfile
        assert 'conda-meta/msgpack-python-*.json' in text, dockerfile
        assert '--strict-channel-priority' in text, dockerfile

    worker_runtime = read('worker/Dockerfile').split('FROM ubuntu:24.04', maxsplit=1)[1]
    assert 'WORKDIR /app' in worker_runtime


def test_deployed_images_apply_os_security_updates():
    for dockerfile in ('Dockerfile', 'worker/Dockerfile', 'api/Dockerfile'):
        text = read(dockerfile)
        assert 'apt-get update' in text, dockerfile
        assert 'apt-get upgrade --yes' in text, dockerfile
        assert 'rm -rf /var/lib/apt/lists/*' in text, dockerfile


def test_runtime_dependencies_include_fixed_security_versions():
    requirements = read('api/requirements.txt')
    for requirement in (
        'fastapi==0.142.2',
        'starlette==1.7.0',
        'setuptools>=78.1.1',
        'msgpack>=1.2.1',
    ):
        assert requirement in requirements


def test_deployed_images_include_database_migrations():
    assert 'COPY api/alembic.ini /app/api/alembic.ini' in read('Dockerfile')
    assert 'COPY api/migrations /app/api/migrations' in read('Dockerfile')
    assert 'COPY alembic.ini ./alembic.ini' in read('api/Dockerfile')
    assert 'COPY migrations ./migrations' in read('api/Dockerfile')
    assert 'alembic' in read('api/requirements.txt')


@pytest.mark.parametrize('name,app_env', [('staging', 'staging'), ('production', 'production'), ('preview', 'preview')])
def test_environment_examples_are_isolated_and_secret_free(name, app_env):
    text = read(f'env/{name}.example')
    assert f'APP_ENV={app_env}' in text
    assert 'SEED_DEMO=false' in text
    for line in text.splitlines():
        if line.startswith(('JWT_SECRET=', 'ADMIN_PASSWORD=', 'BUCKET_SECRET_ACCESS_KEY=')):
            value = line.split('=', 1)[1]
            assert value.startswith('<') or value.startswith('${{'), line


def test_repository_hygiene_passes():
    spec = importlib.util.spec_from_file_location('check_repo_hygiene', ROOT / 'scripts' / 'ci' / 'check_repo_hygiene.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.check(module.tracked_files()) == []


def test_repository_hygiene_detects_forbidden_files():
    spec = importlib.util.spec_from_file_location('check_repo_hygiene', ROOT / 'scripts' / 'ci' / 'check_repo_hygiene.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    problems = module.check(['customer/block_01.laz', 'api/.env', 'api/pla_qc.db', 'data/COLLECTION.xlsx', 'api/.env.example'])
    assert len(problems) == 4
    assert not any('api/.env.example' in p for p in problems)
