---
name: pla-release
description: Validate and prepare a JSAN PLA Quality Validation Workbench change for preview, staging, or production release.
---

Use this skill when a user asks to release, deploy, promote, hotfix, or assess production readiness for the PLA QC Workbench.

1. Read `AGENTS.md`, `docs/PRODUCTION_ENVIRONMENTS.md`, and `docs/RELEASE_RUNBOOK.md`.
2. Identify the target environment and verify it does not share database, bucket, JWT secret, or admin credentials with production unless the target is production.
3. Run the required repository checks from `AGENTS.md`.
4. For production, verify `APP_ENV=production`, PostgreSQL, `STORAGE_MODE=s3`, explicit CORS, no demo seed, and strong non-default secrets.
5. Check `/health/live` and `/health/ready` after deployment.
6. Report the exact commit/build, environment, checks performed, deployment impact, and rollback path.
7. Never print secret values.
