# Profile Imported Project Deletion ExecPlan

## Outcome

Admins can review imports grouped by project on the account Profile page and permanently delete one whole eligible project, including uploaded LiDAR/GeoJSON/Excel, converted COPC data, and all project-owned records. The Production LiDAR list remains view-only; per-file deletion is removed.

## Current behavior

- `web/assets/modules/profile.js` and `web/index.html` implement the account Profile page and admin-only cards.
- `web/assets/modules/production-data.js` currently renders per-LiDAR delete buttons and calls `DELETE /api/projects/{project_id}/uploads/{file_id}`.
- `api/app/main.py` has a guarded per-LiDAR delete route and project/file/block listing routes.
- `api/app/rbac.py` includes the newly added `upload.delete` permission.
- Project data spans `Project`, `DatasetFile`, `ProcessingJob`, `LidarBlock`, poles, annotations, geo features, findings, assignments/presence, workflow versions, QC runs, corrections, review records, and notifications. `AuditLog` is intentionally not project-FK-owned.
- `DatasetFile` object keys and converted block keys may be referenced from other projects, especially linked QC projects.

## Constraints and invariants

- ADMIN and SUPER_ADMIN only may list imports or delete projects; enforce on the API, not only the UI.
- Refuse deletion for active processing, any APPROVED/ARCHIVED version, linked QC projects, or object keys referenced outside the target project.
- Never delete another project's rows or shared objects.
- Delete exact source and derived object keys; treat missing objects as already deleted so failed storage deletion can be retried.
- If object storage fails, keep database records intact and return a retryable error.
- Preserve historical audit records and record the project deletion.
- Keep customer source data immutable except for this explicit, audited destructive action.
- No schema migration is expected.
- Do not overwrite or revert unrelated existing worktree changes.

## Design

- Add `project.delete` to ADMIN and SUPER_ADMIN permissions.
- Add an admin-only endpoint returning project summaries and grouped file metadata for Profile; avoid browser-side N+1 requests.
- Add `DELETE /api/projects/{project_id}` with server-side guard checks, exact object-reference checks, full dependent-record cleanup, and a `DELETE_PROJECT` audit row.
- Add an Imported projects card on Profile with one confirmed delete action per project; refresh project/workspace selection after deletion.
- Remove the per-file delete UI, `upload.delete` permission, per-file DELETE route, and obsolete tests. Keep Manage LiDAR as a non-destructive navigation shortcut to the source list.

## Implementation sequence

1. Add focused API tests for project listing/deletion, RBAC, blockers, relational cleanup, shared storage references, storage errors, and retry.
2. Implement RBAC and project summary/delete endpoints with explicit child-record cleanup ordering; run focused API tests.
3. Add the Profile card, loading/error/empty states, grouped metadata, confirmation, and success refresh; add frontend regression coverage.
4. Remove per-file deletion UI/API/permission and update the Manage LiDAR shortcut/tests to remain view-only.
5. Bump all web asset versions consistently with `python scripts/set_web_version.py <version>`.
6. Run required compilation, full API suite, JavaScript syntax checks, and browser layout/interaction verification.

## Tests

- Unauthorized delete returns 401; non-admin delete/list returns 403; ADMIN and SUPER_ADMIN happy paths.
- Successful delete removes target project data and exact object keys, retains prior audit records, and adds a deletion audit record.
- Active jobs, approved/archived versions, linked QC projects, shared source keys, and shared COPC keys return 409 without relational cleanup.
- Storage deletion error leaves relational records intact; retry succeeds when storage recovers.
- Frontend tests cover admin-only display, grouped LiDAR/GeoJSON/workbook rows, project-level delete action, and absence of per-file delete controls.
- `python -m compileall api/app api/worker.py`
- `cd api && pytest -q`
- `node --check web/assets/app.js` and `node --check` for every `web/assets/modules/*.js`
- Verify 1920x1080 Production layout and four-view maximize/minimize/restore behavior.

## Rollout

Deploy to local first, then preview, staging, and production. Confirm the configured storage identity can delete all required object keys in a non-production environment before enabling the action in production.

## Rollback

Revert the API/UI release to restore the prior application behavior. Project data already permanently deleted cannot be restored by code rollback; recovery requires the organization's storage/database backup policy. Preserve deletion audit records.

## Decision log

- 2026-10-08: Use project as the import grouping key; no new import ID or schema migration.
- 2026-10-08: Use one project-level delete endpoint instead of sequential per-file deletes to avoid UI-driven partial project cleanup.
- 2026-10-08: Restrict visibility and deletion to ADMIN/SUPER_ADMIN; use a dedicated `project.delete` permission.
- 2026-10-08: Refuse deletion when processing, approved/archived versions, linked QC projects, or shared storage objects make removal unsafe.
- 2026-10-08: Keep prior audit records and append a project deletion audit record.
- 2026-10-08 (review): A project deletes only objects under its own key prefix. A QC dataset's file/block rows point at its Production dataset's objects; those are borrowed, never deleted, so QC datasets can be deleted (previously every QC dataset was refused). An own-prefix object used elsewhere still refuses the deletion.
- 2026-10-08 (review): Row deletions are staged and flushed before storage is touched, then committed; a storage failure rolls everything back (previously storage went first, so a database failure left records pointing at deleted files).
- 2026-10-08 (review): The import list reports can_delete/blocked_reason and borrowed ("shared") files; the UI asks for the project name to be typed before deleting.

## Progress

- [x] 2026-10-08: Design spec approved.
- [x] 2026-10-08: API and RBAC implemented; focused tests pass (6, incl. QC dataset borrowing Production LiDAR).
- [x] 2026-10-08: Profile UI implemented (blocked reasons, shared files, typed-name confirmation); per-file delete removed.
- [x] 2026-10-08: pytest 216 passed; node --check all modules; browser check 7/7 on an isolated DB copy and storage folder (deleted).
