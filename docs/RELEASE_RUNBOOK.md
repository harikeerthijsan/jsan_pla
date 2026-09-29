# Release runbook

## Before merge
- Review PR diff and Codex summary.
- CI: pytest, compileall, JS syntax, production-config unit tests.
- No secrets, `.env`, database files, customer workbook/LiDAR, or generated COPC in Git.

## Preview/PR
- Use isolated preview resources or sanitized fixtures.
- Validate affected routes and reviewer UX.

## Staging
- Deploy the exact release candidate.
- Run `/health/live` and `/health/ready`.
- Smoke test login, dataset creation, direct upload, processing queue, pole mapping, Profile/Cross/3D, reviewer decision.
- Compare at least one profile with MicroStation/TerraScan after profile logic changes.

## Production
- Confirm production-only environment variables and object-storage credentials.
- Confirm `APP_ENV=production`, PostgreSQL, `STORAGE_MODE=s3`, explicit CORS, `SEED_DEMO=false`.
- Deploy/promote only after staging sign-off.
- Verify `/health/ready`, login, project list, and one read-only existing dataset view.
- Avoid initiating a test LAS conversion in production unless an approved production smoke dataset exists.

## Rollback
- Roll frontend back to previous known-good deployment.
- Roll API/worker to previous image/commit together when protocol/schema compatibility requires it.
- Never roll back a database schema destructively. Use forward-compatible migrations and documented downgrade only when verified.
- Source objects remain immutable; derived processing can be re-run after application rollback.
