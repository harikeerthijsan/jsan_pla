# Switch a dataset's workbook format when its Excel is replaced

## Outcome

Replace Excel asks which format the new Excel is (PLA-1 single ZoneName sheet, or PLA-2 COLLECTION workbook). A
PLA-1 dataset can take a PLA-2 Excel (and the other way round) with the same poles; from then on the dataset works
as the new format, and Download Excel produces the output in the new Excel's format.

## Current behavior

- `project.workbook_format` (`api/app/models.py`) drives the only format-specific behaviour:
  - Download Excel (`web/assets/modules/production-data.js` `downloadCollectionWorkbook`): PLA-2 builds the COLLECTION
    workbook from saved points (`/production-workbook/collection`, `api/app/collection_workbook.py`); PLA-1 returns the
    latest Excel with Workbook Data edits (`/production-workbook/latest`).
  - Import / process-lidar / Replace Excel refuse an Excel of the other format (`check_workbook_format`, `api/app/main.py`).
- Saved LiDAR points, the point form, the Workbook Data tab and the pole import (`ingest.parse_workbook`) do not depend
  on the format. Points are keyed by pole Internal ID and survive an Excel replacement.
- Replace Excel (`apply_workbook_replacement`) retires (SUPERSEDED, never deletes) the previous Excel and its Workbook
  Data edits, and queues a LIDAR_INGEST job that re-imports poles.

## Constraints and invariants

- Customer source files stay immutable; the previous Excel is superseded, not deleted.
- A format change must be explicit (chosen by the user), verified against the Excel's detected layout, and audited.
- No schema change: `workbook_format` already exists.
- Same permissions as today (`upload.create` + `processing.run`).

## Design

- API: `POST /api/projects/{id}/production-workbook/{file_id}/apply` takes an optional body `{workbook_format}`.
  - Chosen format ≠ detected format → 422, the current Excel is kept.
  - Chosen format ≠ dataset format → the Excel must be detected as the chosen format; then `project.workbook_format`
    switches, logged as `CHANGE_WORKBOOK_FORMAT` and in the `REPLACE_PRODUCTION_WORKBOOK` audit detail.
  - No body → today's behaviour (the Excel must match the dataset's format).
  - Response adds `workbook_format` and `format_changed`.
- UI: the Replace Excel dialog gets a format select (default: the dataset's format) and the same detection hint as
  the import dialog; it refuses a clash before uploading, sends the choice, and updates the dataset's format after.

## Implementation sequence

1. API change + tests (switch PLA-1→PLA-2, PLA-2→PLA-1, chosen≠detected rejected, no body unchanged).
2. Replace Excel dialog + frontend test; bump asset version.

## Tests

- `python -m compileall api/app api/worker.py`
- `cd api && pytest -q` (new tests in `tests/test_workbook_format.py`, `tests/test_production_frontend.py`)
- `node --check` on `web/assets/app.js` and every `web/assets/modules/*.js`

## Rollout

Push to `main` → Railway redeploys; Coolify redeploys from `main`. No migration.

## Rollback

Revert the commit. Datasets that switched keep their new `workbook_format`, which the previous release reads normally.

## Decision log

- Switch only on Replace Excel, never silently on detection: the user picks the format and the server verifies it.
- PLA-2 → PLA-1: PLA-1 output stays "the Excel plus Workbook Data edits"; saved points are not written into the
  ZoneName sheet (PLA-1 never did). Writing them is a separate decision for the user.

## Progress

- [x] API + tests (2026-10-29: `test_replace_excel_switches_the_workbook_format_when_chosen`)
- [x] Replace Excel dialog + frontend test (2026-10-29: `test_replace_excel_asks_for_the_format_and_can_switch_it`)
- [ ] Browser check of the dialog at 1920×1080 (not possible from the dev session: Chrome could not reach the local app)
- [ ] Decide whether PLA-1 output should also write saved points into the ZoneName sheet
