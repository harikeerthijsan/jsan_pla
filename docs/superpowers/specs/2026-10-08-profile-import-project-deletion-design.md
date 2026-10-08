# Imported Project Management and Deletion Design

## Outcome

Add an admin-only **Imported projects** manager to the account Profile page. Each imported project is listed as one import bundle with its LiDAR source files, GeoJSON, and Excel/workbook. An administrator can permanently delete the whole project and its project-owned records in one action.

Remove the existing per-LiDAR-file deletion UI and API. Keep the Production LiDAR source list available for viewing.

## Scope and invariants

- A project is the grouping key for an import; no new import identifier is introduced.
- Only ADMIN and SUPER_ADMIN can see the manager or delete projects.
- The delete endpoint rechecks authorization and all safety conditions server-side.
- Preserve existing protections: refuse while project processing is active, if any project version is APPROVED or ARCHIVED, if the project is referenced by a linked QC project, or if any storage object is shared outside the project.
- Delete all exact uploaded and derived object keys owned by the project, including uploaded LiDAR, GeoJSON, workbooks, converted COPC blocks, and processing outputs recorded on jobs.
- Delete project-owned relational data, including version/workflow/QC records, files, blocks, poles, annotations, geometry, findings/reviews, assignments, presence, and project notifications.
- Preserve audit history and add a `DELETE_PROJECT` record describing the actor, project, and deleted object keys.
- Do not alter or delete data owned by other projects.
- No database schema migration is expected.

## API and authorization

- Add a dedicated `project.delete` permission for ADMIN and SUPER_ADMIN.
- Add an admin-only import listing endpoint returning project metadata and file metadata grouped by project. Avoid issuing one API request per project from the browser.
- Add `DELETE /api/projects/{project_id}`. The endpoint validates all blockers and storage references before deleting any data.
- Missing storage objects count as already deleted, making a retried delete safe. On storage deletion failure, retain all project rows and return an error so the administrator can retry.
- Keep existing audit rows because `AuditLog` entities are not foreign-key children of projects.

## Profile UI

- Add a wide Imported projects section to the account Profile page.
- Each project row shows its name/status and files grouped by LiDAR, GeoJSON, and Excel/workbook, including filenames and sizes when available.
- Add one destructive **Delete import** action per project with explicit confirmation and a pending/disabled state.
- On success, remove the project row and refresh the workspace project selector/state if it referenced the deleted project.
- Hide the manager for non-admin users and while the forced-password-change Profile flow is active.
- Remove per-file delete buttons and the individual LiDAR DELETE endpoint. Retain the non-destructive Production LiDAR list and its navigation shortcut without delete-oriented wording or focus behavior.

## Failure handling

- Project-not-found returns 404.
- Active processing, approved/archived versions, linked QC datasets, and shared object references return 409 without changing database records or deleting storage objects.
- Storage errors return a clear failure and leave database records intact. Since object deletion may be partially accepted by storage, the operation is retryable: already-missing keys are treated as successful, and the project records remain until all keys are deleted.
- The final relational cleanup and deletion audit record are committed together after storage deletion succeeds.

## Regression coverage

- Unauthenticated delete is rejected; non-admin delete is forbidden; ADMIN and SUPER_ADMIN can delete an eligible import.
- Successful deletion removes every project-owned record and exact project object, while retaining audit history and recording the deletion.
- Active processing, approved/archived versions, linked QC projects, shared source objects, and shared COPC objects prevent deletion without database cleanup.
- Storage failure leaves project rows and permits a successful retry after storage recovers.
- Profile listing is admin-only, groups file roles per project, and the UI exposes one project delete action with no per-file delete controls.
- Preserve and update coverage for the Manage LiDAR shortcut so it remains non-destructive.

## Verification

- `python -m compileall api/app api/worker.py`
- `cd api && pytest -q`
- `node --check web/assets/app.js` and every `web/assets/modules/*.js`
- Verify the Production layout at 1920x1080 and the four-view maximize/minimize/restore workflow.
