# Test Report — Dynamic v3.1 Profile Deployable

Date: 2026-09-29

## Automated tests executed for this package

```text
pytest: 10 passed
Python compileall: PASS
Browser JavaScript syntax (node --check): PASS
Railway IaC syntax (node --check): PASS
Bundled API + worker startup smoke test: PASS
Static frontend and /health HTTP smoke test: PASS
```

Coverage includes:

- dynamic project/upload API preparation
- generic workbook parser
- seed integrity baseline
- profile coordinate transform (`station`, `offset`, `z`)
- delivery feature projection into Plan/Profile/Cross views
- deterministic section cache keys
- analysis-frame API for two poles
- section job creation with `job_type=SECTION`
- FastAPI authentication via TestClient
- same-origin frontend, API, and docs routing
- Railway Storage Bucket CORS configuration
- production startup rejection for incomplete bucket credentials

## Live-PDAL validation boundary

The build environment used to package this artifact does not include the PDAL executable, therefore the final PDAL `readers.copc` section-extraction subprocess was not executed here against a real customer point cloud.

The supplied Railway worker image installs PDAL 2.10.2 from conda-forge. The user's PLA development workstation has already validated PDAL 2.10.2 reading/writing the project COPC files and rendering the resulting COPC in Potree. Run `scripts/verify_profile_stack.ps1` and one real profile extraction as the deployment smoke test.

## Release assessment

**Deployable for JSAN internal pilot / staging.** Before customer production use, complete the pilot gate in `PRODUCTION_READINESS.md`, especially SOW rule-matrix signoff and real profile comparison against MicroStation/TerraScan.
