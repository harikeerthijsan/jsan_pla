# Check the Excel before upload; load poles without an Internal ID and set it later

## 1. Outcome
- **Problems found before anything uploads.** When importing a Production dataset, the Excel is checked as soon as it is chosen, before any LiDAR uploads. The user sees:
  - which required columns are missing (Internal ID, Pole Number, Latitude/Longitude or X/Y);
  - which rows are wrong (no Pole Number, duplicate Internal ID, an Internal ID that isn't a whole number).
- **Blank Internal IDs no longer block the import.** Poles whose Internal ID cell is blank are loaded anyway, as "Internal ID not set".
- **Set the ID in the Production view.** For a pole without one, the user types the Internal ID and saves. The pole and all its work move to that ID, and the Excel gets the value in that pole's row (a derived updated workbook; the upload stays unchanged).

## 2. Current behavior
- **The Excel is only parsed after LiDAR conversion.** `ingest.parse_workbook` runs inside the `LIDAR_INGEST` job, after the conversion that can take a long time (`processor.process_job`).
  - Missing columns: `detect_pole_sheet` raises "Workbook must contain a pole catalogue with Internal ID, Pole Number and either latitude/longitude or X/Y".
  - Any blank or invalid Internal ID: `rows_by_header(require_identity=True)` raises.
  - Either way the user only learns of it at the end, and the whole import fails.
- **Pole identity is `poles.internal_id`** (int). It is referenced by:
  - `production_annotations.pole_internal_id`, `production_geo_features.pole_internal_id`;
  - `pole_assignments.pole_internal_id`, `pole_presence.pole_internal_id`;
  - `scene_features.internal_id`, `notifications.pole_internal_id`.
- **The Workbook Data editor finds a pole's row by Pole Number**, so it already works when the Internal ID cell is blank.

## 3. Constraints / invariants
- **AGENTS #5:** the uploaded Excel is never modified. Setting an ID writes a new `WORKBOOK_EDITED` file, like the Workbook Data editor does.
- **AGENTS #6:** the change is audited (`SET_POLE_INTERNAL_ID`, old → new, file ids).
- **AGENTS #9:** the new endpoint is tested signed out (401), with the wrong role (403) and on the happy path.
  - Filling a **missing** ID needs `production.annotate`.
  - Changing an existing ID keeps needing `workbook.edit_internal_id` (admins), as the Workbook Data tab does today.
- **No schema change.** A pole without an Internal ID gets a provisional negative id, `-(sheet row number)`.
  - It is stable across re-imports of the same Excel and can never collide with a real ID, which is a positive whole number.

## 4. Design
- **Shared checker:** `ingest.check_production_workbook(path) -> {errors, warnings, pole_count, missing_internal_ids}`.
  - Used by the import dialog (`POST /api/production/workbook-format` now returns the check too), by `/process-lidar` (refuses with 422 when there are errors, before queuing), and by the Excel replacement apply.
- **Parser:** blank Internal ID → provisional `-(row)`; a non-blank, non-integer ID is still an error.
- **Set the ID:** `PUT /api/projects/{id}/poles/{internal_id}/internal-id {internal_id}`.
  - The new ID must be a positive whole number that no other pole in the dataset uses.
  - Every reference in the dataset moves in one transaction.
  - The pole row's Internal ID cell is written into a new `WORKBOOK_EDITED` copy of the latest workbook, keeping x14 dropdowns.
- **COLLECTION export:** poles still without an ID are left out, and the summary says how many. Their sheet rows can't be identified until the ID is set.
- **UI:**
  - The import dialog lists errors (and blocks the upload) and warnings.
  - The pole list and pole header show "Internal ID not set", with an input and a **Save ID** button.

## 5. Tests
`cd api && pytest -q`. New tests cover:
- the checker (missing columns named; blank IDs are a warning; duplicate and invalid IDs are errors);
- parsing with blank IDs;
- process-lidar refusing a bad Excel;
- the set-ID endpoint: 401, 403, 409 duplicate, 422 invalid, happy path moving annotations, and the Excel cell written;
- the export skipping provisional poles.

Browser: import dialog messages, and setting an ID in the Production view.

## 6. Rollout / rollback
- **Rollout:** local → Railway. No migration.
- **Rollback:** redeploy the previous release. Poles keep whatever IDs were set, and provisional (negative) ones stay until set.

## 7. Decision log
- **Negative provisional IDs** rather than a nullable column: the integer identity is used throughout (URLs, joins, exports), and a migration plus nullable joins would be far riskier.
- **Check in the dialog and again at process-lidar:** the dialog gives early feedback; the server check guarantees it.

## 8. Progress
- [x] 2026-10-16 Checker + parser + process-lidar guard (Production re-imports now prefer the latest WORKBOOK_EDITED, so set IDs survive a reprocess)
- [x] 2026-10-16 Set-ID endpoint + Excel write + export skip. Found on real data: a ZoneName sheet can list one pole on several rows,
  and sample-1 has two poles sharing Pole Number FTG-000046. The ID is written to every row of that Pole Number whose
  Internal ID is blank / the previous id / already the new id; rows carrying another pole's id are left alone.
- [x] 2026-10-16 Import dialog + Production view UI
- [x] 2026-10-16 Tests (tests/test_missing_internal_ids.py; full suite 321 passed, only the unrelated outputs/ hygiene check fails)
  + browser check on a DB copy (dialog errors/notes, "ID not set", invalid/duplicate messages, save, Excel cell written)
