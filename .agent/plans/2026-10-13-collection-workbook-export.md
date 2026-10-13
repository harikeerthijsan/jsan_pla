# Saved points → COLLECTION workbook

## 1. Outcome
Every saved production point is written into the COLLECTION workbook layout and can be downloaded at any time.

The layout:
- one sheet per group: `poles`, `attachments`, `crossarms`, `equipment`, `anchors`, `guys`, `sidewalk_braces`, `span_guys`;
- one row per pole;
- one numbered column set per point, e.g. `swb_{n}_key … swb_{n}_guy_nos`.

When a point number has no columns yet (for example `swb_3` in a sheet that stops at `swb_2`), a new set is inserted with the same field names, header style and widths. It goes directly after the last set for that prefix and before `remarks` (or before the next prefix group).

## 2. Current behavior
- Points are stored in `production_annotations` and exported only as GeoJSON.
- The workbook editor edits one pole's cells and saves a derived `WORKBOOK_EDITED` file. It saves through openpyxl, which drops Excel's x14 "extension" data validations (the key/owner dropdowns that reference the `lut_*` sheets).

## 3. Constraints / invariants
- **AGENTS #5:** the uploaded workbook is never modified. The export is generated on demand from the latest workbook of the active version (`WORKBOOK_EDITED`, else `WORKBOOK`) plus the saved points, so it always reflects every saved point.
- **AGENTS #4:** customer workbooks are not committed. Only the column template (names) is in code.
- **AGENTS #7:** no silent CRS conversion.
  - Lat/lon come from the stored WGS84 values that are already computed per point.
  - `*_elev_ft` is the point Z in project units, converted to feet only when the project unit is metres. The download reports the conversion it used.
- **Excel structure is preserved:**
  - Tables (ref and columns) grow with inserted columns.
  - Standard and x14 data validations are shifted, and copied onto new columns.
  - The column-B `pole_number` formula is kept and copied to appended rows.
- **Read permission:** `project.read`, the same as the GeoJSON export.

## 4. Mapping
| Point | Sheet / columns |
|---|---|
| Pole_Base | `poles`: latitude, longitude, bottom_elev_ft, first_pole, last_pole, environment; other_type/other_id/other_attach_N → other_1_* |
| Pole_Top | `poles`: top_lat, top_lon, top_elev_ft |
| arm_n | `crossarms`: arm_n_key, arm_n_owner, arm_n_tip_lat, arm_n_tip_lon, arm_n_elev_ft |
| comm_n / util_n | `attachments`: comm_n_* / util_n_* (lat, lon, elev_ft plus attributes) |
| eq_n, anc_n, guy_n, sgy_n, swb_n | their sheets, the same pattern (only the columns the template has, e.g. guys has no lat/lon) |
| other_n | `poles`: other_n_lat, other_n_lon, other_n_elev_ft |

Attribute key → column: strip the prefix (and a stray `1_` in `util_1_usage`). For example `swb_anchor_no` on swb_3 → `swb_3_anchor_no`.

If the project's workbook is not in the COLLECTION layout (for example sample-1's single `ZoneName` sheet), a workbook in that layout is generated with one row per pole.

## 5. Validation
- **Unit tests:**
  - mapping;
  - dynamic set insertion (header order, table ref and columns, validations shifted and copied);
  - x14 validations survive;
  - appended poles;
  - elevation units;
  - generated layout for non-collection workbooks.
- **API:** auth matrix (unauthenticated 401) and the happy path.
- **Browser:** save points, click Download, and inspect the file.

## 6. Progress
- [x] `api/app/collection_workbook.py`: mapping, dynamic column sets, tables, dropdowns (standard and x14), template rows, generated layout
- [x] `GET /api/projects/{id}/production-workbook/collection` (project.read), audited as DOWNLOAD_COLLECTION_WORKBOOK
- [x] Workbook Data editor saves now keep the x14 dropdowns (`restore_validation_extensions`)
- [x] "Download Excel" button in Saved points
- [x] Tests: 7 in `test_collection_workbook.py`; full suite 275 passed
- [x] Dry run on the real COLLECTION_Sample1.xlsx (5.2 s); browser download on sample-1 (generated layout)
