# One-click deliverable package and in-app notifications

## 1. Outcome
- Every APPROVED dataset version has a **Download package** button on the Delivery page. It produces one ZIP containing:
  - the updated Production Excel and the QC Excel that was checked
  - `annotations.geojson` of all saved Production points
  - `findings-report.xlsx` (Summary, Findings with reviewer decisions, Corrections, Poles)
  - `manifest.json` with SHA-256 checksums and provenance
  - a short README
- The package is built and stored when the version is approved, so it reflects exactly what was approved. Versions approved before this release get theirs built on first download, and the manifest records that.
- A bell in the header shows unread notifications:
  - "QC found 3 issues on your poles"
  - "Correction requested on pole 1130560E"
  - "Pole 1130560E fixed by JSAN004 — ready for re-check" ("All corrections fixed" for the last one)
  - "You were assigned 12 poles"
  - "v2 approved — deliverable package ready"
  - "QC failed"
  Clicking a notification opens the dataset and pole it refers to.

## 2. Current behavior
- Delivery shows versions and corrections. Nothing is exported except the edited Excel and the per-user annotations GeoJSON.
- No notifications. Events happen in `processor.py` (QC run end), `create_correction`, `resolve_correction`, `approve_version`, and `team.assign_poles`.

## 3. Constraints / invariants
- Source objects stay immutable. The package is a derived artifact under `{qc_project}/versions/v{n}/deliverables/`.
- Large files are not proxied by FastAPI in production: the download returns a presigned URL.
- Findings stay traceable to dataset, version, pole, rule, field, reviewer, decision and timestamp, all in the report.
- Uploaded workbook text is untrusted. Report cells that start with `= + - @` are written as text (no formula injection).
- Notifications respect the admin-invisibility rule (users see "an admin"), never notify the actor about their own action, and a notification failure never fails the triggering action.
- Additive migration only.

## 4. Design
- Migration `20261007_0010`: `notifications` (user_id, kind, title, body, project_id, pole_internal_id, link_json, created_at, read_at).
- `app/notifications.py`:
  - helpers: `notify_qc_finished`, `notify_correction_requested`, `notify_correction_resolved`, `notify_version_approved`, `notify_poles_assigned`
  - router: `GET /api/notifications`, `POST /api/notifications/{id}/read`, `POST /api/notifications/read-all`
  - Pole "owner" = the assignee, else the last person who saved a point on the pole.
- `app/deliverables.py`: `build_package`, `ensure_package`.
  - `GET /api/projects/{id}/versions/{vid}/deliverable` (workspace.delivery): 409 unless APPROVED; returns `{url, filename, generated_at, sha256, files[]}`.
  - `approve_dataset` builds the package after commit. A failure is logged and the package is retried on download.
- `production.annotations_feature_collection` is shared by the existing GeoJSON download and the package.
- Frontend: bell, count and panel (polled every 60 s), click to navigate, mark read; Delivery version rows get **Download package** for APPROVED versions.

## 5. Implementation sequence
Migration/model → notifications module + hooks → deliverables module + endpoints → tests → frontend → browser check.

## 6. Tests
`pytest -q`, including `tests/test_deliverables_notifications.py`:
- package contents, checksums and formula-injection guard
- 409 before approval; built at approval and lazily for older approvals
- notification recipients and wording, self-suppression, admin masking
- read and read-all
- auth (401/403)

## 7. Rollout / 8. Rollback
Staging, then production. No new variables. Rollback = redeploy the previous release; the new table is ignored and stored packages remain as harmless derived objects.

## 9. Decision log
- Excel findings report rather than PDF: `openpyxl` is already a dependency, and adding a PDF library would add image size and scan surface. The Excel version is also filterable.
- Packages are frozen at approval instead of always regenerated, because annotations and the edited Excel keep changing after approval.
- In-app notifications only; there is no email infrastructure to rely on yet.

## 10. Progress
- [x] 2026-10-07 implemented: migration 0010, `notifications.py` (+ hooks in processor, corrections, approval, assignments), `deliverables.py`, shared `annotations_feature_collection`, bell/panel UI, Download package button.
- [x] 2026-10-07 fixes found in testing:
  - the header now stacks above Plotly's modebar (z-index 1001), which blocked the notification panel in the QC tab
  - naive SQLite timestamps are serialised with an explicit UTC offset (`models.iso_utc`), so "just now" no longer shows "5 h ago"
  - the doubled full stop in correction messages is removed
  - the Production Excel falls back to the original import if nothing predates the approval
- [x] 2026-10-07 pytest 139 passed ×3. Browser on a throwaway DB copy: 10/10 (bell, navigation, read/read-all, re-check notice, approval → package download with all files).
