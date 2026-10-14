# Workbook format per Production dataset: PLA-1 (ZoneName) or PLA-2 (COLLECTION)

## 1. Outcome
Importing a Production dataset requires choosing a **Workbook format**:
- **PLA-1:** a single sheet named ZoneName, with readable column names. Saved points are *not* written automatically. The reviewer fills each pole's columns by hand in the **Workbook Data** tab, saves, and downloads the updated Excel.
- **PLA-2:** the COLLECTION workbook (poles / attachments / crossarms … sheets plus lut_* lookups). Saved points are written into it automatically, and **Download Excel** returns the filled COLLECTION workbook. This is the existing behaviour.

A workbook that doesn't match the chosen format is refused with a clear message, so a wrong export can't happen silently.

## 2. Current behavior
- **Upload:** `productionUploadForm` (`web/assets/modules/production-shell.js`) creates the project (`POST /api/projects`), uploads the workbook, GeoJSON and LiDAR, then calls `POST /process-lidar`. There is no format choice.
- **Download Excel:** the Saved points button always calls `GET /production-workbook/collection` (`collection_workbook.py`). For a workbook not in the COLLECTION layout, a COLLECTION workbook is generated.
- **Workbook Data tab:** `GET/PUT /poles/{id}/workbook` edits one pole's row, saves a derived `WORKBOOK_EDITED` file and audits it. The source is untouched. `GET /poles/{id}/workbook-download` returns the latest edited file.

## 3. Constraints / invariants
- **AGENTS #5:** source workbooks stay immutable. PLA-1 edits keep using the derived `WORKBOOK_EDITED` files.
- **AGENTS #1:** nothing is hard-coded to sample datasets. The format is detected from the sheet structure, not from file names.
- **Local SQLite compatibility:** the new column is nullable. Projects without a format are detected from their current workbook on first use, then saved.
- **No new auth surface:**
  - The new download uses `project.read`, the same as the existing workbook downloads.
  - The format is set at project creation, which needs `project.create`.

## 4. Design
- **Schema:** `projects.workbook_format`, String(10), nullable, holding `PLA-1` or `PLA-2`. Migration `20261014_0017` adds it when missing; downgrade is a no-op.
- **Detection:** `detect_workbook_format(bytes)` in `collection_workbook.py`.
  - `PLA-2` when the COLLECTION group sheets are present (`poles` and `attachments`).
  - `PLA-1` when the workbook is a single sheet, or has a sheet named ZoneName / Zone Name.
  - Otherwise `None` (unknown).
- **API:**
  - `ProjectIn.workbook_format` is optional (`PLA-1` | `PLA-2`); the Production import UI makes it mandatory.
  - `project_dict` includes `workbook_format`.
  - `POST /process-lidar` reads the uploaded workbook and returns 422 when it doesn't match the chosen format. When the project has no format, the detected one is stored.
  - Replace Excel (`/production-workbook/{file}/apply`) runs the same check.
  - New `GET /production-workbook/latest` downloads the latest workbook (edited, else original). It is the PLA-1 "Download Excel" and is audited as `DOWNLOAD_PRODUCTION_WORKBOOK`.
  - `GET /production-workbook/collection` returns 409 for PLA-1 projects, with directions to the Workbook Data tab.
- **UI:**
  - The import dialog gets a required **Workbook format** select, with no default.
  - The project header shows the format.
  - The Saved points **Download Excel** button routes by format, and a hint explains the PLA-1 manual flow.

## 5. Implementation sequence
1. Migration, model, detection, API with tests.
2. Upload dialog field and the create body.
3. Download routing, hint and header.
4. Asset version bump and browser check.

## 6. Tests
- `cd api && pytest -q`.
- New `tests/test_workbook_format.py`:
  - detection of both layouts;
  - create stores the format;
  - process-lidar refuses a mismatch and accepts a match;
  - legacy projects (no format) get detected;
  - the latest download needs sign-in (401) and returns the edited file;
  - the collection export refuses PLA-1.
- Browser: import dialog requires the format, and Download Excel routes correctly.

## 7. Rollout
local → preview → staging → production. The migration runs on API start (`initialize_schema`) and only adds a nullable column.

## 8. Rollback
Redeploy the previous release. Older code ignores the extra nullable column, so no data is lost.

## 9. Decision log
- PLA-1 doesn't get automatic point writing. Its columns (attachment owner / messenger cable …) don't map one-to-one to points, and the user chose manual entry.
- Format is detected on the server (sheet structure) rather than in the browser, so no xlsx parser is needed client-side.
- The check runs in the import dialog (before any upload) and again at process-lidar (server-side backstop). Rejected alternative: checking when each upload completes, which happens before all files are uploaded and is per file.

## 10. Progress
- [x] 2026-10-14 Schema (migration 20261014_0017), detection and API with tests (`tests/test_workbook_format.py`; full suite 293 passed)
- [x] 2026-10-14 Upload dialog: required Workbook format, a live "This Excel is…" hint, and a mismatch refused before any upload
  (`POST /api/production/workbook-format` reads the Excel only; it needs `upload.create`, tested for 401/403/200)
- [x] 2026-10-14 Download routing (PLA-1 → `/production-workbook/latest`, PLA-2 → `/collection`, legacy falls back on 409), header shows the format,
  CORS exposes Content-Disposition / X-Collection-Summary / X-Workbook-Edited so cross-origin downloads keep their names
- [x] 2026-10-14 Browser check on the dev app: hint, mismatch refusal (no dataset created), sample-1 detected as PLA-1, original-Excel note
- [x] 2026-10-14 Existing datasets on deployed servers: the worker backfills formats on start (`app/workbook_format.py`,
  `backfill_workbook_formats`, idempotent, one failure doesn't stop the rest). Datasets imported without an Excel stay unset;
  admins set them from the header (`PUT /api/projects/{id}/workbook-format`, `project.create`, refused if it contradicts the
  Excel, audited as SET_WORKBOOK_FORMAT; tested for 401/403/422/200). Local dev run: detected 3, no workbook 23, failed 0.
