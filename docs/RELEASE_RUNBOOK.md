# Release runbook

Branch flow: `feature/*` → PR into `staging` → Railway **staging** → PR `staging` → `main` → Railway **production**.
Railway deploys through its GitHub integration with **Wait for CI** enabled, so a commit whose CI
workflow fails is never deployed. No Railway or Vercel token is stored in GitHub.

## Before merge (every PR)
- Review PR diff and agent/Codex summary.
- CI (`.github/workflows/ci.yml`) must be green:
  - `test`: compileall, `pytest -q` (includes production-guard, health and release-config tests), `node --check`.
  - `hygiene`: `scripts/ci/check_repo_hygiene.py` (no `.env`, DB, LiDAR, workbook, COPC, key files; no workflow secrets).
  - `image-app`: builds the root `Dockerfile` (the image Railway deploys), checks PDAL/GDAL/SQLite, serves `/health/ready`, and proves the production guard rejects unsafe config.
  - `image-worker`: builds `worker/Dockerfile` and imports the processing modules.
- Local equivalent: `.\scripts\run_ci_local.ps1` (image builds run only if Docker is installed).
- No secrets, `.env`, database files, customer workbook/LiDAR, or generated COPC in Git.

## Preview/PR
- Railway PR environments (if enabled) fork from **staging**, never production; `APP_ENV=preview`.
- Use isolated preview resources and synthetic/sanitized fixtures only.
- Validate affected routes and reviewer UX.

## Staging
- Merge the reviewed PR into `staging`; Railway waits for CI on that commit, then deploys.
- Run **Actions → Verify deployment** with `environment=staging` and the staging URL
  (checks `/health/live`, `/health/ready`, `app_env=staging`, `storage_mode=s3`).
- Smoke test login, dataset creation, direct upload, processing queue, pole mapping, Profile/Cross/3D, reviewer decision.
- Compare at least one profile with MicroStation/TerraScan after profile logic changes.
- Record the staging deployment ID and commit SHA in the promotion PR.

## Production
- Open a PR `staging` → `main` containing exactly the commit(s) accepted in staging, and merge it with a
  merge commit so production runs the same tree that staging accepted.
- Confirm production-only variables (`env/production.example`): `APP_ENV=production`, PostgreSQL,
  `STORAGE_MODE=s3`, no wildcard `CORS_ORIGINS`, `SEED_DEMO=false`, unique JWT/admin secrets.
  `.\scripts\production_preflight.ps1 -Environment production` checks the shape without printing values.
- Railway waits for CI, then only switches traffic after `/health/ready` returns 200 (timeout 180 s).
  A failed healthcheck leaves the previous deployment serving.
- Run **Verify deployment** with `environment=production`; then check login, project list, and one
  read-only existing dataset view.
- Avoid initiating a test LAS conversion in production unless an approved production smoke dataset exists.

## Rollback
Decide within the first 30 minutes after a production deploy; the previous deployment is the known-good release.

1. **Application (Railway):** service `pla-qc` → Deployments → previous successful deployment →
   **Rollback**. This restores that image *and* its variables. API and worker are in one image, so they
   always roll back together.
2. **Git:** open a PR reverting the merge commit on `main` (and on `staging`) so the next autodeploy does
   not reintroduce the change. Never force-push `main` or `staging`.
3. **Healthcheck path:** if a deploy is blocked only because `/health/ready` is failing on an older image
   that lacks it, set the service healthcheck back to `/health` in Railway settings, roll back, then fix forward.
4. **Guard refusal:** if the new deployment fails with `Unsafe production configuration`, the previous
   deployment keeps serving. Fix the named variable in Railway; do not weaken the guard.
5. **Frontend (Vercel, if used):** promote the previous known-good deployment.
6. **Database:** never roll back a schema destructively. This release has no schema change. Future schema
   changes must be forward-compatible (expand → migrate → contract) so the previous image still runs.
7. **Data:** source objects remain immutable; derived COPC/profile artifacts can be re-run after rollback.
8. Record the incident: deployment IDs, commit SHAs, time to recover, root cause.
