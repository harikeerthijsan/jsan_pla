# ExecPlan: Pole Workbook Editor

## Outcome

Production users can switch the annotation panel to Workbook Data, view all workbook rows and columns belonging to a selected Pole Number across worksheets, edit all fields except Pole Number, save version-scoped workbook changes, and download the complete updated workbook. GeoJSON Pole Number matching is exact and does not silently fall back to nearest geometry. Source workbook uploads remain immutable.

## Current Behavior

- `web/index.html` has the production Point Attributes annotation form but no workbook editor.
- `api/app/processor.py` stores the `poles` worksheet manifest on `Pole`; other worksheet records are only available in the uploaded workbook.
- `api/app/geojson_import.py` stores original GeoJSON properties and may use ID or nearest-pole matching for the general overlay.
- `DatasetFile` and `VersionFile` support versioned artifacts; storage helpers support local and S3-compatible buckets.
- `openpyxl` is already installed. Approved design: `docs/superpowers/specs/2026-10-05-pole-workbook-editor-design.md`.

## Constraints / Invariants

- Never modify or overwrite a source workbook. Generated workbooks use separate derived object keys and file records.
- Keep project/version isolation; read the active version's edited workbook first, otherwise its uploaded workbook.
- Join using normalized Pole Number only for this editor. Pole Number is read-only. Missing or ambiguous GeoJSON matches disable editing; do not use nearest geometry as fallback.
- Validate all worksheet names, rows, columns, selected pole, and snapshot ID server-side. Prevent submitted text from becoming a spreadsheet formula.
- Writes require `production.annotate`; reads and downloads require `project.read`. Test unauthorized, wrong-role, and happy path.
- Do not proxy LAS/LAZ/COPC binaries. Do not add a schema migration unless the existing artifact/version tables prove insufficient; if so, stop and revise plan.
- Do not rerun QC automatically. Existing QC-derived results remain as they were until the standard processing workflow runs again.

## Design

- Add a small `api/app/workbook_editor.py` for normalized Pole Number matching, workbook row inspection, safe cell edits, and in-memory XLSX generation.
- Resolve source and latest `WORKBOOK_EDITED` records through the active `DatasetVersion`'s `VersionFile` entries. Save each successful change as a new `DatasetFile` role `WORKBOOK_EDITED`, linked to the same version; audit changed worksheets/columns without storing cell values.
- Add authenticated read, save, and download endpoints. Return a snapshot file ID on read; require it on save and reject stale snapshots with 409. Serve the bounded XLSX as an attachment.
- Add tabs in the production annotation panel. Workbook Data renders matching rows from every worksheet using original headers, with Pole Number readonly. Reload on pole/project/version changes; enable save only with exact unique GeoJSON Pole Number match and write permission.

## Implementation Sequence

1. Add unit tests for normalized headers/values, strict GeoJSON Pole Number matching, duplicate/missing matches, all-sheet row discovery, and workbook round-trip edits.
2. Implement workbook inspection/edit helpers using temporary/in-memory workbooks; run those tests immediately.
3. Add API models/routes for read/save/download, version artifact selection/registration, optimistic conflict detection, permissions, and audit records; add API coverage.
4. Add workbook tab markup and scoped CSS; wire loading, editable values, Pole Number locking, save, and download into production state in `web/assets/app.js`; add frontend wiring tests.
5. Run compileall, API pytest with basetemp outside the repo, and Node syntax check. Verify the 1920x1080 four-view workspace and maximize/minimize/restore are unchanged.

## Tests

- Unit/API: strict GeoJSON exact match (no nearest fallback), normalization and duplicate handling, every worksheet and repeated matching row, Pole Number write rejection, formula-as-text rejection, stale snapshot conflict, storage failure preserves previous active artifact, version isolation, source bytes unchanged, valid downloaded XLSX.
- Auth: project.read read/download; production.annotate save; unauthorized, wrong-role, and permitted requests.
- Frontend: tabs, pole selection refresh, dynamic sheet columns/rows, read-only Pole Number, missing/ambiguous match state, save feedback, download wiring.
- Commands from repo root: `python -m compileall api/app api/worker.py`; `$env:PYTHONPATH="api"; python -m pytest -q --basetemp "C:/Users/admin/AppData/Local/Temp/jsan_pytest"`; `node --check web/assets/app.js`.
- Visual: 1920x1080 four-view layout and maximize/minimize/restore after frontend changes.

## Rollout

Validate with generated, non-customer workbook/GeoJSON fixtures locally; then preview; then isolated staging before production. No production/staging DB or bucket sharing. No migration expected.

## Rollback

Revert editor UI and endpoints. Retain immutable source files and versioned derived artifacts under normal retention policy. Do not reset databases or delete source files.

## Decision Log

- Show all matching worksheet rows and all columns, not just the poles worksheet.
- `Pole Number` remains read-only because it is the approved GeoJSON join key.
- GeoJSON matching requires exact normalized Pole Number; the existing nearest matching remains only for the overlay.
- Original workbook is immutable; each save writes a new versioned derived XLSX artifact.
- Workbook changes do not automatically rerun QC.

## Progress

- [x] Approved design captured in `docs/superpowers/specs/2026-10-05-pole-workbook-editor-design.md`.
- [x] ExecPlan created before application code changes.
- [x] Implement helper functions and workbook round-trip tests.
- [x] Implement authorized, versioned API endpoints, immutable derived artifact lifecycle, concurrency checks, and audit records.
- [x] Implement production panel tabs, searchable pole picker, dynamic all-sheet fields, read-only Pole Number, save, and download.
- [x] Preserve the loaded pole form and unsaved edits across Point Attributes / Workbook Data tab switches; show loading and saving activity indicators.
- [x] Run required checks: compileall; both JavaScript syntax checks; full pytest (106 passed, 1 warning).
- [x] Visual check at 1920x1080: workbook pole picker visible and synchronized; no horizontal overflow; four-view maximize and restore work.
