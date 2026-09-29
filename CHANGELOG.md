# Changelog

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
