# Generalized Pole Workbook and GeoJSON Import

## Outcome

Production and QC accept customer workbooks and GeoJSON files whose pole identity and location columns use common naming variants. The system validates the required identity/location data before processing, preserves all source workbook columns and GeoJSON properties, and continues to support the existing PLA workbook without data loss or silent CRS conversion.

## Current behavior

- `api/app/ingest.py` requires a worksheet named `poles`, exact lowercase schema keys, and several PLA-specific sheets and attributes.
- `api/app/workbook_editor.py` normalizes spaces/underscores for `Pole Number`, but still requires the exact `poles` worksheet and uses pole number alone to find rows.
- `api/app/geojson_import.py` preserves arbitrary properties and transforms geometry, but heuristically chooses any property producing the most ID matches.
- Production and QC both call the same `parse_workbook` pipeline in `api/app/processor.py`.
- The Production GeoJSON card already renders all source properties. Workbook Data already renders all columns from rows matched to the selected pole.

## Constraints and invariants

- Existing PLA workbooks and local SQLite databases remain compatible.
- Source workbooks and GeoJSON remain immutable; edited workbook versions remain derived files.
- CRS assignment and transformation stay explicit. Latitude/longitude means WGS84; X/Y means the project CRS.
- At least one stable pole identity is required per catalogue row. Conflicting or duplicate identity values must not be silently matched.
- Customer-defined columns and GeoJSON properties are preserved with their original names.
- No credentials, customer data, uploaded binaries, or database files are committed.

## Design

1. Introduce shared header normalization and alias recognition for `internal_id`, `pole_number`, `latitude`, `longitude`, `x`, `y`, and `z`.
2. Detect the primary pole worksheet by its canonical identity/location columns, preferring a sheet named `poles` for backward compatibility.
3. Require both `internal_id` and `pole_number` in the primary catalogue and one location source: latitude+longitude or X+Y. Accept optional Z.
4. Preserve every non-empty source column in the pole manifest and return primary-sheet metadata from parsing.
5. Let Workbook Data find related rows on any sheet by pole number first and internal ID as a consistency check/fallback. Keep both identity columns read-only according to the existing authorization rules.
6. Make GeoJSON matching deterministic using recognized pole-number/internal-ID aliases, with both-identities matching first, then one identity, then the existing bounded nearest-point fallback. Expose all properties unchanged.
7. Use workbook X/Y directly for LiDAR block mapping; transform latitude/longitude from WGS84 only when X/Y is absent.
8. Add validation and regression coverage for aliases, arbitrary sheet names/columns, X/Y-only workbooks, conflicts, duplicates, and legacy PLA input.

No database schema change is planned: normalized identity/location values fit the existing `Pole` fields and arbitrary source values remain in `manifest_json`/`properties_json`.

## Implementation sequence

- [x] Add shared schema detection and focused unit tests.
- [x] Generalize workbook ingestion while preserving PLA-specific QC rules when their sheets/fields exist.
- [x] Generalize Workbook Data row discovery and update protection.
- [x] Make GeoJSON identity matching deterministic and conflict-safe.
- [x] Update processor and QC section pole-to-LiDAR mapping for X/Y/Z sources.
- [x] Add a read-only GeoJSON Data tab showing all properties for the selected pole.
- [x] Run required regression and syntax checks.

## Tests

- `python -m compileall api/app api/worker.py`
- `cd api && pytest -q`
- `node --check web/assets/app.js`
- Targeted tests for:
  - `Internal ID` / `internal_id` and `Pole Number` / `pole_number` aliases.
  - Non-`poles` primary sheet detection.
  - Arbitrary columns preserved and editable.
  - WGS84 latitude/longitude and project-CRS X/Y/Z sources.
  - Missing required identity/location fields rejected with actionable errors.
  - Duplicate/conflicting identifiers rejected or left unmatched.
  - GeoJSON Point Z and arbitrary properties preserved.
  - Existing PLA fixture output remains compatible.

LiDAR mapping changes will also require comparison against a trusted project fixture/MicroStation workflow when customer LiDAR is available; automated bounding-box tests provide the repository-level regression meanwhile.

## Rollout

1. Local: exercise legacy and generalized fixtures and inspect Production/QC pole selection.
2. Preview: import synthetic alias variants and a sanitized customer-shaped workbook/GeoJSON.
3. Staging: process a representative production-sized dataset in isolated Postgres/object storage and compare pole-to-block mappings.
4. Production: deploy only after staging evidence, database/bucket backups, and normal release approval.

## Rollback

Re-deploy the previous application/worker image. No destructive migration is introduced. Existing source files remain immutable, so affected datasets can be reprocessed with the previous worker. Any generalized-format dataset unsupported by the old worker remains stored but should not be reprocessed until the generalized version is restored.

## Decision log

- 2026-10-07: Keep both `internal_id` and `pole_number` required in the primary workbook catalogue because current routes, annotations, QC findings, and workbook editing depend on both.
- 2026-10-07: Do not require latitude/longitude on every worksheet; related sheets join by identity. Repeating location everywhere would create avoidable conflicts.
- 2026-10-07: Treat GeoJSON geometry as the authoritative GeoJSON coordinate source; X/Y/Z properties remain ordinary source attributes.
- 2026-10-07 (review): `Height` is pole length, not elevation, and `Pole ID` commonly holds the tag number, so neither is an alias. GeoJSON files with no recognised identity columns fall back to the earlier best-property matching. Workbook X/Y with base/top elevations builds the pole line at X/Y.
- 2026-10-07: Avoid a database migration by storing project-CRS workbook X/Y/Z in the existing manifest and deriving mapping coordinates during processing.

## Progress

- 2026-10-07: Current ingestion, processing, workbook-editor, and GeoJSON matching paths inspected; plan created.
- 2026-10-07: Generalized import and UI implemented without a schema migration. Full suite: 167 tests passed; Python compile and all frontend JavaScript syntax checks passed.
- 2026-10-07: Review fixes (aliases, empty sheets, X/Y pole line, legacy GeoJSON fallback, encoding) plus regression tests. Full suite: 170 passed.
