# Admin LiDAR Source Deletion

## Outcome

An ADMIN or SUPER_ADMIN can permanently remove an incorrectly uploaded LiDAR source from the Production LiDAR sources list. The source object, its derived COPC objects, and their live catalogue rows are removed together, and the deletion is audited.

## Current behavior

`api/app/main.py` supports preparing and completing uploads but has no delete endpoint. `api/app/storage.py` can create/read objects but cannot delete them. `web/assets/modules/production-data.js` renders imported LiDAR rows without actions.

## Constraints/invariants

- Only ADMIN and SUPER_ADMIN may delete uploaded LiDAR.
- Customer source objects remain immutable while retained; deletion is allowed only for unapproved, unshared correction workflows.
- Never break approved/archived evidence, linked QC datasets, active processing, or saved Production annotations.
- Delete both the selected source and derived COPC objects, without deleting objects still referenced elsewhere.
- Record actor, project, file, affected blocks, and object keys in the audit log.
- Support both local storage and S3-compatible storage.

## Design

- Add `upload.delete` only to ADMIN and SUPER_ADMIN permissions.
- Add a storage deletion helper with local path validation and S3 error handling.
- Add `DELETE /api/projects/{project_id}/uploads/{file_id}` for `LIDAR_SOURCE` records.
- Reject deletion for approved/archived versions, active jobs, shared source/COPC objects, or dependent saved annotations.
- Delete version links, block rows, and the dataset-file row; clear pole mappings/verifications tied to removed blocks; reset the current project/version to `UPLOADING`; and add an audit record.
- Add an admin-only Delete button to each LiDAR source row with explicit confirmation and reload the viewer after success.

## Implementation sequence

1. Add permission and storage primitive.
2. Add the guarded API endpoint and audit behavior.
3. Add the Production UI action and styling.
4. Add backend authorization/storage regression tests and frontend wiring coverage.
5. Bump the shared web asset version and run required checks.

## Tests

- Unauthorized request returns 401.
- Non-admin request returns 403.
- ADMIN and SUPER_ADMIN can delete safe sources.
- Source and derived objects, version links, block/file rows, and pole mapping are removed; an audit entry remains.
- Approved, shared, active-processing, and annotation-dependent sources return 409 without deleting data.
- Run `python -m compileall api/app api/worker.py`.
- Run `cd api && pytest -q`.
- Run `node --check web/assets/app.js` and every `web/assets/modules/*.js`.
- Verify the 1920x1080 Production layout and maximize/minimize/restore behavior.

## Rollout

Deploy local, then preview, staging, and production. Confirm storage credentials include delete-object permission in non-local environments before enabling the action.

## Rollback

Roll back the API/UI release. Already deleted source data cannot be reconstructed by code rollback and must be restored from the organization's storage backup/versioning policy, so approved/shared/in-use evidence is blocked from deletion.

## Decision log

- 2026-10-08: Chose a dedicated `upload.delete` permission instead of reusing `upload.create`, so only ADMIN and SUPER_ADMIN receive destructive access.
- 2026-10-08: Chose refusal over cascading into linked QC datasets or saved annotations.
- 2026-10-08: Chose synchronous source/COPC deletion so the UI reports completion only after storage accepts the deletion.

## Progress

- [x] 2026-10-08: Investigated upload, version, storage, processing, and Production UI relationships.
- [x] 2026-10-08: Implemented backend permission, guarded API deletion, local/S3 deletion, cleanup, and audit behavior.
- [x] 2026-10-08: Added the permission-gated Production source Delete action and confirmation flow.
- [x] 2026-10-08: Added regressions; focused tests passed (22), and the full API suite passed (213).
- [x] 2026-10-08: Python compilation and all JavaScript syntax checks passed; 1920x1080 Production UI and four-view maximize/minimize/restore were verified in headless Chrome.
- [x] 2026-10-08: Added a visible, permission-gated Manage LiDAR header shortcut after user feedback that the collapsed source controls were hard to discover.
