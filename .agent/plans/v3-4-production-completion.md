# v3.4 production completion

## Outcome

Close the remaining code-ready production-foundation gaps without regressing the deployed PDAL/GDAL/SQLite stack: introduce a real, additive Alembic migration path; replace wildcard bucket CORS with environment-derived explicit origins; and provide a repeatable, machine-readable profile-parity evidence harness. Keep the existing dynamic ingestion, linked Delivery/QC workflow, RBAC, worker leases, and four evidence views unchanged.

Production OIDC activation, the remaining PLA SOW rule matrix, and final MicroStation/TerraScan acceptance remain explicit external gates because the repository does not contain an approved identity-provider registration, customer rule specification, trusted reference data, or approved tolerances.

## Current behavior

- `origin/main` already contains the v3.4 operational workflow, API RBAC, dataset versions, corrections, worker leases/heartbeats/retries, upload validation, and a manual profile-parity checklist.
- `api/app/db.py` still initializes production schema with `Base.metadata.create_all`.
- The Railway entrypoint serializes schema initialization, but there is no revision history or migration command.
- `.railway/railway.ts` configures bucket CORS with `*`.
- `docs/PROFILE_PARITY_ACCEPTANCE.md` describes manual evidence but there is no structured evidence format or comparison command.
- Production OIDC is not enabled; named local accounts are the documented interim mode.

## Constraints and invariants

- Do not modify or overwrite source workbook/LiDAR objects.
- Do not change CRS assignment or projection behavior.
- Do not weaken staging/production startup guards.
- Preserve existing SQLite developer databases and existing PostgreSQL deployments.
- Migration rollout must be additive; no destructive table/column operations.
- Preserve the pinned PDAL 2.10.2, GDAL 3.13.3, and libsqlite compatibility stack.
- Do not invent customer acceptance tolerances, PLA rules, IdP endpoints, tenant IDs, or credentials.
- Staging and production resources remain isolated.

## Design

### Schema migrations

- Add Alembic configuration under `api/` and an initial additive revision representing the current v3.4 schema.
- Add an application migration runner that executes `upgrade head` under the existing PostgreSQL advisory lock.
- The baseline revision creates registered SQLAlchemy tables with `checkfirst=True`, allowing both a new database and a legacy database previously initialized with `create_all` to adopt the revision safely.
- Keep a narrowly scoped `create_all` fallback only for test metadata setup where tests explicitly request it; production startup uses Alembic.
- Copy migration resources into the Railway/API images and add regression tests for fresh and existing SQLite databases.

### Bucket CORS

- Derive an explicit origin from `BUCKET_CORS_ORIGINS`, `CORS_ORIGINS`, or Railway's public domain.
- Reject wildcard or missing bucket origins in staging/production.
- Remove the committed wildcard from Railway IaC and document custom-domain overrides.

### Profile parity evidence

- Add a JSON evidence schema/example containing dataset/version, CRS, pole/span IDs, corridor settings, point-count/bounds/station-offset-elevation summaries, tolerance source, reviewer, and result.
- Add a command that validates evidence structure and compares numeric observations only when project-approved tolerances are supplied.
- Add synthetic, non-confidential tests; do not claim MicroStation/TerraScan acceptance without real reviewer evidence.

### External gates

- Document the exact inputs needed to activate OIDC: issuer, client ID/audience, authorization/token/JWKS endpoints, approved claims, and JSAN role mapping. Do not ship an unverified authentication flow.
- Record the missing customer SOW rule matrix and trusted profile data/tolerances as release blockers rather than fabricating behavior.

## Implementation sequence

1. Add this ExecPlan and create a scoped feature branch from current `origin/main`.
2. Introduce Alembic and additive compatibility migration tests.
3. Route API/worker/Railway startup through migrations and update images.
4. Harden bucket CORS and its environment tests.
5. Add profile-parity evidence validator/comparator and tests.
6. Update environment, security, release, and implementation-status documentation.
7. Run required Python, pytest, JavaScript, hygiene, and Docker checks.
8. Push the feature branch. Promote through `staging` and then `main` only after CI and staging acceptance gates are satisfied.

## Tests

- `python -m compileall api/app api/worker.py api/railway_entrypoint.py api/migrations`
- `cd api && python -m pytest -q`
- `node --check web/assets/app.js`
- `node --check web/config.js`
- `python scripts/ci/check_repo_hygiene.py`
- Build root, API, and worker Docker images because Dockerfiles change.
- Migration scenarios: empty SQLite database; legacy SQLite database with current tables but no `alembic_version`; repeated upgrade is idempotent.
- Bucket CORS scenarios: explicit origin accepted; Railway domain derived; wildcard/missing strict configuration rejected.
- Parity evidence scenarios: valid evidence; missing traceability; comparison without approved tolerance rejected; within/outside tolerance results.

## Rollout

1. Local migration/tests using only synthetic SQLite data.
2. PR/preview with no production credentials.
3. Back up staging PostgreSQL, deploy the exact feature commit, run migration, and verify `/health/ready`.
4. Upload/process approved staging data and complete the profile-parity record.
5. Verify roles and correction/version workflow.
6. Promote the exact staging-approved tree to `main`; run production migration before API/worker traffic starts.

## Rollback

- Roll the app image back to the previous Railway deployment.
- The migration is additive and its downgrade intentionally does not drop customer tables; application rollback remains compatible with the preserved existing schema.
- Never delete `alembic_version`, source objects, dataset versions, findings, or reviewer history during rollback.
- Revert the Git merge through a PR so autodeploy cannot reintroduce the failed revision.

## Decision log

- 2026-09-30: Use an adoptive initial migration with `checkfirst=True` so existing production databases are not recreated or destructively stamped.
- 2026-09-30: Do not implement or activate speculative OIDC without an approved JSAN IdP registration and claims contract.
- 2026-09-30: Do not invent profile tolerances or remaining SOW rules; provide auditable input formats and keep acceptance external.
- 2026-09-30: Preserve the combined Railway app topology for this patch; splitting API/worker changes failure and scaling behavior and needs a separate staging capacity decision.
- 2026-09-30: Refresh Miniforge from `25.3.1-0` to the current official `26.7.2-0` after Trivy blocked both images; retain exact PDAL/GDAL/libsqlite pins and require CI smoke tests.
- 2026-09-30: Use Miniforge only as a build stage and copy the pinned `/opt/conda/envs/pla` environment into a security-updated Ubuntu runtime. This removes unused vulnerable `rattler` libraries from the deployed image without relocating or repinning the geospatial environment.
- 2026-09-30: Upgrade FastAPI/Starlette and explicitly require fixed setuptools/msgpack versions in response to actionable HIGH findings from the staging image scan.
- 2026-09-30: Preserve the worker runtime working directory explicitly after the multi-stage boundary; Docker stage-local `WORKDIR` settings do not carry into the final stage.
- 2026-09-30: Constrain fixed setuptools and msgpack versions in the Conda solve as well as Python requirements. A pip upgrade alone left vulnerable Conda metadata visible to Trivy even though the imported wheel was newer.
- 2026-09-30: Assert the imported setuptools/msgpack versions while building, then remove only their duplicate Conda records after pip becomes authoritative for those two packages. Retain all native/geospatial Conda records so the final image remains meaningfully scannable.

## Progress

- [x] Synced local working tree to `origin/main` (`0ea8417`).
- [x] Created `feature/v3.4-production-completion`.
- [x] Added ExecPlan.
- [x] Added and tested migration path.
- [x] Hardened bucket CORS.
- [x] Added profile-parity evidence harness.
- [x] Updated documentation.
- [x] Completed Python compile, 75-test pytest, JavaScript syntax, hygiene and diff checks after dependency remediation.
- [ ] Completed Docker image builds and vulnerability scans (image build/smoke passed; targeted remediation for the reported findings is awaiting CI).
- [x] Pushed feature branch and exact commit to `staging` for CI/deployment gating.
- [ ] Staging acceptance completed.
- [ ] Promoted to `main`.
