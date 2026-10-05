# Pole Workbook Editor Design

**Status:** Draft for user review  
**Date:** 2026-10-05

## Outcome

In the LiDAR Production annotation panel, users can switch between **Point Attributes** and **Workbook Data**. For a selected pole, Workbook Data shows every matching row and every original column from each worksheet in the uploaded Excel workbook. All cells are editable except `Pole Number`, which is the immutable join key. Saving creates a versioned updated workbook that can be downloaded; the original upload is never changed.

## Current Behavior

- `web/index.html` contains the production annotation panel, pole selector, and production upload dialog. There is no workbook editor tab.
- `api/app/processor.py` parses production workbooks. In LiDAR-only production mode, it stores the `poles` worksheet row as `Pole.manifest_json`; records from the other worksheets are not available as editable records in the API.
- `api/app/main.py` exposes the pole list and GeoJSON features, and production annotation save/delete endpoints. The project retains `source_workbook_key` for the source upload.
- `api/app/geojson_import.py` stores GeoJSON properties and auto-matches point features by detected IDs, with a nearest-pole fallback. That general overlay behavior must not be used as a silent fallback for the workbook editor's Pole Number join.
- `DatasetFile` and `VersionFile` in `api/app/models.py` and `api/app/workflow.py` provide storage and dataset-version associations for artifacts without adding database columns.
- `api/app/storage.py` supports local and S3-compatible storage. `openpyxl` is already a project dependency.

## User Experience

1. Add tabs to the current production annotation panel: **Point Attributes** and **Workbook Data**. Keep the existing annotation form and behavior under Point Attributes.
2. On Workbook Data, selecting a workbook pole loads matching data dynamically from every worksheet. A worksheet with multiple rows for the pole displays each row; each row exposes all original workbook columns, including blank cells.
3. Inputs use the source header names. `Pole Number` is visible but read-only. All other cells are editable.
4. Show the GeoJSON match state for the selected pole. Missing or ambiguous GeoJSON Pole Number matches and duplicate workbook Pole Numbers are reported clearly and disable editing for that pole; do not select a pole by nearest geometry.
5. Provide **Save changes** and **Download updated Excel** actions. The download contains the complete workbook, not only the selected pole or worksheet.
6. Keep edits and selection scoped to the active dataset version. Switching projects or versions reloads the corresponding workbook state.

## Matching and Data Integrity

- Treat normalized `Pole Number` as the sole editor join key. Header normalization is case-insensitive and treats spaces and underscores equivalently; value normalization trims whitespace and applies the existing ID normalization rules without converting a different textual pole number into another value.
- Locate the pole's point feature in the imported GeoJSON using a GeoJSON property whose normalized header is `Pole Number`. The value must exactly match the selected workbook pole's normalized `Pole Number`. GeoJSON internal-ID or nearest-coordinate matches alone are insufficient for this editor.
- Locate workbook rows in all worksheets using their `Pole Number` column and exact normalized value equality. Do not infer membership from row proximity or coordinate distance.
- Keep `Pole Number` read-only in the UI and reject attempts to modify it at the API boundary. This preserves the GeoJSON association and prevents changing the key from detaching all associated rows.
- Revalidate project, active-version workbook, selected pole, worksheet names, row indexes, headers, and GeoJSON match on every read and save. Do not trust client-supplied row coordinates or column names without checking them against the workbook.
- Do not evaluate user-entered formulas or allow text updates to become executable spreadsheet formulas. Preserve the source workbook's existing worksheet layout and unrelated rows/cells when writing changes.

## Persistence and API

- Add a focused workbook editor module to read workbook metadata and matching rows, validate edits, and write the updated workbook using `openpyxl`.
- Add a read endpoint scoped to project and pole that returns worksheet names, matching row identifiers, original headers and values, Pole Number, the GeoJSON match state, and the source/derived file ID for the workbook snapshot. Require `project.read`.
- Add a save endpoint accepting cell updates and the workbook snapshot file ID for the selected pole. Require `production.annotate`. Validate that the submitted snapshot is still the active workbook, every update targets a currently matched row, all referenced columns exist, and no update targets the Pole Number column. Reject stale snapshots with a conflict response.
- Resolve the workbook from the active `DatasetVersion`: use its latest `WORKBOOK_EDITED` artifact when present; otherwise use its uploaded `WORKBOOK`. Do not use a project-global workbook from another version.
- For each save, write a new derived `.xlsx` object under that version's derived-artifact prefix, register it as a `DatasetFile` with role `WORKBOOK_EDITED`, and associate it with the same `VersionFile`. The original source workbook and earlier derived artifacts remain immutable.
- Add an authenticated download endpoint that returns the latest edited workbook for the active version, with an attachment filename and the correct XLSX media type. The workbook is bounded by the existing workbook size limit; LAS/LAZ/COPC data is not routed through this endpoint.
- Record an audit event containing actor, project/version, pole identity, affected worksheet and row counts, and changed column names. Do not copy cell values into audit details.
- Use existing `production.annotate` permission for writes and `project.read` for reads/downloads. Do not weaken RBAC.
- No schema migration is expected: use the existing free-form `DatasetFile.role` and `VersionFile` association. If implementation discovers these tables cannot safely represent derived artifacts, stop and revise this design before adding schema.

## Errors and Edge Cases

- No uploaded workbook or GeoJSON: show a clear unavailable state; do not silently fall back to a different project's or version's files.
- No exact GeoJSON Pole Number match, multiple matching features, or duplicate workbook Pole Numbers: report the condition and prevent writes for that pole.
- A stale client row/column reference or workbook snapshot after a version switch or concurrent save: reject with a conflict and reload the current workbook state.
- Invalid or oversized workbook, malformed workbook, and storage failures: return safe actionable errors and leave the previous derived workbook intact.
- Save is atomic from the user's perspective: only register the new artifact after successful write/upload; failed saves must not replace the last downloadable workbook.

## Tests

- Unit tests for normalized header/value matching, multiple worksheet rows per pole, blank cells, missing/duplicate keys, strict GeoJSON Pole Number matching, and rejection of Pole Number/formula edits.
- API tests for unauthorized, wrong-role, and permitted read/save/download behavior; project/version isolation; stale-snapshot conflict handling; and auditing without cell values.
- Workbook round-trip tests proving edits apply across sheets, unrelated cells survive, the source workbook bytes remain unchanged, and the downloaded XLSX contains the saved values.
- Frontend regression tests for tab switching, selected-pole refresh, dynamic fields for every worksheet, read-only Pole Number, save errors/success, and download action wiring.
- Required repository checks: `python -m compileall api/app api/worker.py`; `cd api && pytest -q` (with pytest temp directory outside the repository); `node --check web/assets/app.js`. If frontend behavior is changed, verify production layout at 1920x1080 and check maximize/minimize/restore remain functional.

## Rollout and Rollback

- Validate locally with a synthetic workbook containing multiple worksheets and a GeoJSON fixture with an exact Pole Number property. Then validate in preview with non-production data before staging.
- No production schema migration is planned. Keep production and staging databases/buckets isolated, and do not use customer workbook content in tests or plans.
- Rollback by reverting the editor endpoints and UI. Original workbook uploads remain unchanged; derived artifacts are versioned and can be retained or removed according to normal artifact retention policy. No destructive database reset is required.

## Decisions

- **All worksheets, not only `poles`:** selected-pole data may be distributed across worksheet rows; all matching rows and all columns must be available.
- **Pole Number is read-only:** user confirmed this key must not be edited; it anchors the GeoJSON-to-workbook crosswalk.
- **Strict GeoJSON key match:** nearest-coordinate and internal-ID fallback remain available to the existing GeoJSON overlay, but are not sufficient for workbook editing.
- **Derived workbook output:** source uploads are immutable per repository invariant; save creates a separately stored updated Excel artifact.
- **Versioned artifacts:** the updated workbook belongs to the active dataset version and must not leak into another revision.
- **No automatic QC rerun:** saving workbook edits only writes the updated workbook artifact; QC-derived results remain unchanged until the existing processing workflow is run again.