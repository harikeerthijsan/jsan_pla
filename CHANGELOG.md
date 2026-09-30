# Changelog

## 3.4.1-operational — 2026-09-30

- Added an additive Alembic baseline that adopts existing v3.4 SQLite/PostgreSQL databases without dropping customer data.
- Serialized production migrations with the existing PostgreSQL advisory lock before API/worker startup.
- Removed committed wildcard bucket CORS and derive or require explicit browser origins in staging/production.
- Added machine-readable profile-parity evidence validation and approved-tolerance comparison.
- Added pull-request dependency review and Trivy gates for both built container images.
- Documented the external OIDC, PLA rule-matrix, and trusted MicroStation/TerraScan acceptance gates.

## 3.0.0-profile-dev — 2026-09-29

- Replaced single-view reviewer center with synchronized Plan / Longitudinal Profile / Cross Section / 3D workspace.
- Added automatic primary-to-target span frame and nearest-pole fallback.
- Added dynamic target-pole selection and finding-driven span selection.
- Added PDAL COPC profile extraction jobs with spatial bounds, resolution control, rotated-corridor filtering, point sampling and caching.
- Added movable cross-section station controlled from slider or clicks in Plan/Profile.
- Preserved dynamic dataset upload and LAS/LAZ -> COPC workflow.
- Preserved QC findings, review decisions and audit baseline.
- Added local start wrapper to avoid path/cd mistakes.
- Added PDAL driver verification.
- Added architecture, research notes and development backlog.
- Expanded automated tests to 7 passing tests.
