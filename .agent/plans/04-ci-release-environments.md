# ExecPlan — Task 04: CI/CD and environment release gates

Branch: `feature/v3.4-production-foundation`. Source task: `codex_tasks/04-ci-release-environments.md`.

## 1. Outcome
Every pull request is gated by the same checks a production release needs (compileall, pytest,
JS syntax, repository hygiene, and builds of the images Railway actually deploys). Staging is a
persistent, isolated Railway environment. Production deploys only commits whose CI is green and
only cuts over when `/health/ready` returns 200. Rollback is documented. No provider tokens live in Git.

## 2. Current behavior (before this plan)
- Production runs ONE Railway service `pla-qc` built from the root `Dockerfile`
  (conda-forge PDAL 2.10.2 / GDAL 3.13.3 / libsqlite>=3.51) whose `api/railway_entrypoint.py`
  starts uvicorn + `worker.py` in one container. Declared in `.railway/railway.ts`.
- `api/Dockerfile` (python:3.12-slim, no PDAL), `api/railway.json`, `railway-api.json` and
  `railway-worker.json` describe an older split topology and are not what production builds.
- Healthcheck is `/health` (static, no dependency checks). No `/health/live` or `/health/ready`.
- `railway.ts` hard-codes `APP_ENV=production`, so applying it to a `staging` environment would
  make staging claim to be production.
- `api/app/main.py` has no runtime environment guard even though docs claim one; only
  `railway_entrypoint.validate_production_environment()` checks a subset, and only for production.
- Untracked drafts: `.github/workflows/ci.yml` (built the non-deployed `api/Dockerfile`, skipped the
  worker image on PRs), `scripts/run_ci_local.ps1` (`python -m python -m pytest` bug),
  `scripts/production_preflight.ps1` (required `CORS_ORIGINS`, which the same-origin Railway
  deployment does not set), `api/tests/test_production_guard.py` (tests a function that did not exist),
  `env/*.example`.

## 3. Constraints / invariants
- Do not change the root or worker Dockerfile PDAL/GDAL/SQLite packaging.
- Do not weaken `validate_production_environment()`; only extend.
- The new guard must accept the production configuration that is live today
  (Postgres, s3, ≥32-char JWT, non-default ≥12-char admin password, `SEED_DEMO=false`,
  same-origin UI so `CORS_ORIGINS` may be unset).
- CI uses no repository secrets; PR workflows never run with production credentials.
- Keep `/health` response unchanged (existing tests and external monitors).

## 4. Design
- `app/main.py`: `APP_ENV`, `STRICT_ENVIRONMENTS={'production','staging'}`,
  `validate_runtime_environment()` called at lifespan start. Rejects SQLite, non-s3 storage,
  missing/default/short `JWT_SECRET`, missing/default/short `ADMIN_PASSWORD`, wildcard
  `CORS_ORIGINS`, `SEED_DEMO=true`, and an `APP_ENV` that disagrees with Railway's
  `RAILWAY_ENVIRONMENT_NAME` (catches a staging/PR environment duplicated from production that
  still says `APP_ENV=production`, and vice-versa). Expected production environment name is
  configurable via `PRODUCTION_RAILWAY_ENVIRONMENT` (default `production`).
- `/health/live` (process up, no I/O) and `/health/ready` (DB `SELECT 1` + storage configuration
  resolvable; 503 otherwise; never echoes exception text or credentials).
- `railway_entrypoint.py`: apply the existing checks to `staging` as well as `production`.
- `.railway/railway.ts`: derive `APP_ENV` from `ctx.environment`
  (`production`→production, `staging`→staging, anything else→preview) and use `/health/ready`.
- `.github/workflows/ci.yml`: jobs `test`, `hygiene`, `image-app` (root Dockerfile, the deployed
  image, with container smoke tests of `/health/ready` and the production guard), `image-worker`.
  All run on PRs and on pushes to `staging`/`main` (Railway "Wait for CI" requires push runs).
- `.github/workflows/verify-deployment.yml`: manual post-deploy check of `/health/live`,
  `/health/ready` and the reported `app_env` against a URL input. No secrets.
- `scripts/ci/check_repo_hygiene.py`: fails on tracked `.env`, DB, LiDAR, workbook, COPC files and on
  workflows that use `pull_request_target` or reference provider tokens.

## 5. Implementation sequence
1. Guard + health endpoints + tests. 2. Entrypoint staging extension + test.
3. railway.ts. 4. Hygiene script + test. 5. CI + verify workflows + release-config tests.
6. Scripts/env examples/docs/PR template. 7. Full local check run.

## 6. Tests
```
python -m compileall api/app api/worker.py
cd api && pytest -q
node --check web/assets/app.js
python scripts/ci/check_repo_hygiene.py
```
Docker image builds run in GitHub Actions (`image-app`, `image-worker`); Docker is not available on
the authoring workstation.

## 7. Rollout
local → PR (CI green) → merge to `staging` → Railway staging auto-deploys after Wait for CI →
staging acceptance (`verify-deployment` + runbook smoke) → PR `staging`→`main` → Railway production
auto-deploys after Wait for CI and `/health/ready`.

Before the first production deploy of this change, confirm in Railway (read-only):
the production environment is named `production` (or set `PRODUCTION_RAILWAY_ENVIRONMENT`), and
`CORS_ORIGINS` is not `*`. Otherwise the new guard will (correctly) refuse to start and Railway will
keep the previous deployment live.

## 8. Rollback
See `docs/RELEASE_RUNBOOK.md` → Rollback. Code-only change, no schema change: redeploy the previous
Railway deployment (dashboard "Rollback") or revert the merge commit on `main`. If the healthcheck
path change is the problem, set the service healthcheck back to `/health` in Railway settings.

## 9. Decision log
- Kept the single-service topology (API+worker in one container). Splitting is Task 05 territory
  and would change production behavior.
- Deploy via Railway GitHub autodeploy + Wait for CI rather than `railway up` from Actions:
  no `RAILWAY_TOKEN` is needed in GitHub at all.
- Unset `CORS_ORIGINS` is allowed in strict environments because the UI is served same-origin;
  only `*` is rejected. Rejecting empty would break the live production configuration.
- `/health/ready` checks storage *configuration*, not a bucket round-trip, so a transient bucket
  blip cannot fail every deploy; the entrypoint already validates bucket variables.
- Left `api/Dockerfile`, `api/railway.json`, `railway-api.json`, `railway-worker.json` untouched:
  legacy split-topology artifacts, not used by the live service. Flagged for later removal.

## 10. Progress
- [x] Inspection and baseline (10 passed; 3 untracked guard tests failing — missing implementation).
- [x] Guard, health endpoints, entrypoint, railway.ts.
- [x] CI, verification workflow, hygiene script.
- [x] Scripts, env examples, docs, PR template.
- [x] Full local check run (see summary in the PR).
