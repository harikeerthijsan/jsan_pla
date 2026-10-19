# Session work: export, clear and view archives (admins only)

## 1. Outcome
Several teams work on the same imported LiDAR in turns. Between sessions, an admin or super admin uses **Session work**:
1. **Download archive.** One signed JSON file with all of the session's work for the dataset, and who did it:
   - saved points (position, lat/lon, group, fields, pole, parent, created_by / modified_by, timestamps);
   - measurements;
   - pole assignments;
   - pole verification;
   - a per-person summary.
2. **Clear this work.** Deletes exactly what that archive contains, so the next session starts clean. It is only possible right after the export, and is audited.
3. **View an archive.** Importing the file shows the work as a read-only overlay: markers in the LiDAR view, per-person summary, and a list. Nothing current changes. The app also tells whether the file is a genuine, unmodified export of this application (signature).

Users cannot export, clear or view archives.

## 2. Current behavior
- **Points** live in `production_annotations` (with `created_by`, `modified_by`, `created_at`, `updated_at`).
  - Deleting a point keeps an audit snapshot.
  - Pole verification is derived from Pole_Base / Pole_Top points.
  - Pole assignments live in `pole_assignments`.
- **Measurements** exist only in the browser (`production-measure.js`) and are lost on refresh. The user chose to include them, so they are first made persistent.

## 3. Constraints / invariants
- **AGENTS #6 (traceability):**
  - The archive keeps creator, modifier and timestamps for every item.
  - Export, clear and view are audited (`EXPORT_WORK_ARCHIVE`, `CLEAR_WORK_SESSION`, `VIEW_WORK_ARCHIVE`).
  - Deleted points also get the usual `DELETE_PRODUCTION_ANNOTATION` snapshot.
- **AGENTS #9:** every new endpoint is tested signed out (401), with the wrong role (403, a User), and on the happy path.
- **Data safety:**
  - Clearing removes only items listed in an archive that the same admin exported in the last 24 hours, and only if they are unchanged since the export (same revision / timestamp).
  - Anything changed since the export, or anything still referenced as a parent by a newer point, is skipped and reported.
  - An admin never clears work they could not see: a super admin's work is hidden from admins, so it is not in an admin's archive.
- **Untrusted file:** an imported archive is treated as data.
  - Size limit 25 MB; structure validated; strings length-limited.
  - Rendered with escaping.
  - The HMAC signature (server secret) shows whether it was modified.

## 4. Design
- **Migration `20261020_0019`:**
  - `production_measurements` (id, project_id, pole_internal_id, a/b xyz, distance, created_by, created_at);
  - `work_archives` (id, project_id, created_by, created_at, `items_json` with ids and revisions, `counts_json`, cleared_at, cleared_by).
- **API:**
  - `GET` / `POST` / `DELETE /api/projects/{id}/measurements` (read: `project.read`; write: `production.annotate`).
  - `POST /api/projects/{id}/work-archive` (`project.create`) returns the signed JSON file.
  - `POST /api/projects/{id}/work-archive/{archive_id}/clear` (`project.create`).
  - `POST /api/projects/{id}/work-archive/view` (`project.create`, file upload) returns the verified, normalised archive.
- **UI:**
  - The Measurements panel saves, loads and deletes on the server, and shows who measured.
  - A **Session work** button (admins) opens a dialog with the current work per person, Download, Clear, and View-archive.
  - The archive overlay draws violet markers with a "Hide archive" control.

## 5. Tests
`cd api && pytest -q`. New `tests/test_session_work.py` covers:
- auth for every endpoint;
- the export contents and signature;
- clear removes exactly the archived items, skips changed ones and resets pole verification;
- view verifies and refuses modified or oversized files;
- measurements CRUD.

## 6. Rollout / rollback
- **Rollout:** additive migration.
- **Rollback:** redeploy the previous release. The new tables are ignored, and exported archive files stay with the admin.

## 7. Progress
- [x] Migration 20261020_0019, models, measurement API, archive API + tests (tests/test_session_work.py; full suite 340 passed, only the unrelated outputs/ hygiene check fails)
- [x] Measurements persisted in the UI (saved on finish, loaded with the dataset, "· who" on each row)
- [x] Session work dialog + archive overlay. Browser check on a DB copy: export, clear (1 point + 1 measurement), archive verified,
  who-did-what table, Go flies to a point, violet overlay badge and Hide.
  Found while testing: the in-page confirmation rendered behind the modal dialog (top layer); confirmAction now attaches
  to the open <dialog>.
