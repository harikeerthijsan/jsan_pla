# JSAN PLA Quality Validation Workbench — Codex Instructions

## Mission
Build and maintain an industry-grade browser-based PLA quality-validation platform. Preserve the working dynamic ingestion, LAS/LAZ→COPC pipeline, pole-to-LiDAR mapping, synchronized Plan/Profile/Cross/3D evidence views, and reviewer decision flow.

## Repository map
- `web/`: static reviewer UI, Potree integration, synchronized engineering views.
- `api/app/`: FastAPI application, auth, dataset APIs, QC, storage, section/profile analysis.
- `api/worker.py`: background processing entrypoint.
- `worker/Dockerfile`: PDAL-capable worker image.
- `api/tests/`: regression tests.
- `docs/`: architecture, release, security, and environment runbooks.
- `codex_tasks/`: scoped implementation prompts suitable for parallel Codex worktrees.

## Non-negotiable invariants
1. A dataset upload must be dynamic; never hard-code Sample1 or Sample2 records into production logic.
2. Large LAS/LAZ/COPC binaries never pass through Vercel and should not be proxied by FastAPI in production; use presigned object-storage URLs.
3. Production and staging must use separate database and bucket instances.
4. Never commit credentials, customer LiDAR, workbooks, generated COPC, `.env`, or database files.
5. Keep customer source files immutable. Derived COPC/profile artifacts use separate object keys.
6. QC findings must be traceable to dataset/project, pole, rule, source field, reviewer, decision, and timestamp.
7. Do not silently convert source coordinate systems. CRS assignment/reprojection must be explicit and auditable.
8. Preserve the four synchronized evidence modes: Plan, Longitudinal Profile, Cross Section, and 3D Perspective.
9. Any auth/authorization change requires tests for unauthorized, wrong-role, and happy-path behavior.
10. Never weaken production startup guards to make a deployment pass.

## Required checks before declaring a task complete
From repo root:
- `python -m compileall api/app api/worker.py`
- `cd api && pytest -q`
- `node --check web/assets/app.js`
- If Dockerfiles changed: build both API and worker images.
- If frontend changed: verify 1920×1080 four-view layout plus maximize/minimize/restore.
- If LiDAR/profile logic changed: compare at least one profile/cross-section with the trusted MicroStation/TerraScan workflow.

## Change discipline
- Keep patches scoped.
- Add or update regression tests with each bug fix.
- For changes spanning authentication, schema, processing, or deployment topology, create an ExecPlan using `.agent/PLANS.md` before coding.
- Preserve backward compatibility with existing local SQLite developer databases unless the change explicitly introduces a migration.
- For production schema changes, introduce a real migration path; do not rely on destructive recreation.

## Security baseline
Target OWASP ASVS Level 2 practices for this internal/customer-facing business application. Treat uploaded workbooks and LiDAR as untrusted content. Validate extension, media type where reliable, size, object key, and authorization. Do not render user-controlled HTML.

## Environments
- `local`: developer machine, local storage permitted, SQLite permitted.
- `preview`: ephemeral frontend/backend review environment using non-production data.
- `staging`: persistent production-like environment with isolated Postgres and bucket.
- `production`: explicit secrets, PostgreSQL, S3-compatible private bucket, no demo seed, explicit CORS, named users.

Read `docs/PRODUCTION_ENVIRONMENTS.md` and `docs/RELEASE_RUNBOOK.md` before deployment changes.
