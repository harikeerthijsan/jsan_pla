# v3.4 Operational Platform — Implementation Status

## Implemented in this increment
- Linked Delivery and QC workspaces on the same project/dataset records.
- Runtime environment/build identity for LOCAL / STAGING / PRODUCTION.
- Named-user management and API-enforced RBAC for Delivery, QC, program management and customer read-only roles.
- Dataset versions with immutable source object keys.
- QC runs tied to a dataset version.
- Correction requests and Delivery correction queue.
- Revision comparison: NEW / STILL_OPEN / RESOLVED.
- Version approval gate.
- Reviewer decision archive before findings are rebuilt on reprocessing.
- Versioned derived COPC and profile-analysis objects.
- Upload extension and size validation, login abuse throttling and security headers.
- Atomic worker claims, leases, heartbeats, stale lease recovery and bounded retries.
- Deterministic profile projection tests and a MicroStation/TerraScan parity acceptance checklist.

## Preserved
- Existing dynamic COLLECTION + LAS/LAZ/COPC ingestion.
- PDAL 2.10.2 / GDAL 3.13.3 / libsqlite compatibility pins.
- Pole-to-LiDAR mapping including source/pre-pop XY fallback.
- Plan / Longitudinal Profile / Cross Section / 3D Perspective views.
- Maximize, minimize, restore and focus-workspace reviewer controls.
- Direct browser-to-object-storage upload model.

## External dependency still required
Production identity federation (OIDC/SSO and MFA) is not enabled because an approved JSAN identity provider and tenant/application registration have not been supplied. v3.4 therefore deploys named local accounts with RBAC as the production-safe interim mode. The bootstrap administrator credential must be rotated and should not be shared between users.

## Release gate
1. GitHub CI must pass Python, JavaScript, repository hygiene, app image and worker image checks.
2. Prefer Railway staging with isolated Postgres and bucket before production promotion.
3. Run the profile parity acceptance cases in docs/PROFILE_PARITY_ACCEPTANCE.md.
4. Promote staging to main only after smoke testing login, upload, processing, QC evidence, correction, resubmission and approval.
