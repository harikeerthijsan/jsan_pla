# Production LiDAR annotation and measurement workspace

## Outcome

Add an auditable Production workspace where a producer can open an imported LiDAR block, manually pick engineering points, classify them with the supplied production taxonomy, attach Section 3 coding attributes, calculate pole-relative height and point-to-point offsets, and save the work for later editing and QC handoff.

Extend that workspace to import the client's pole workbook in Production, retain its approximate latitude/longitude, and let a producer attach an exact LiDAR pole location. The server transforms the picked native project X/Y into WGS84 longitude/latitude and preserves both source and verified values with user/time/block lineage.

Capture separate LiDAR-picked pole base and pole top elevations and calculate the verified pole height in project units. Preserve the workbook's source bottom/top elevations for comparison.

Display every converted LAS/LAZ/COPC block together as one combined streaming 3D scene. Keep source and derived objects separate in storage and infer the owning source block from a picked coordinate when an annotation is saved.

## Current behavior

- The Production page imports LAS/LAZ/COPC without a workbook and lists converted blocks.
- A converted block can be viewed in Potree, but no point can be selected, classified, measured, or saved.
- The API has projects, source files, LiDAR blocks, audit logs, and role permissions, but no production-annotation model.
- `PLA_Contractor_Scope_of_Work_v.0.3.pdf` Section 3 defines pole, attachment, crossarm, equipment, anchor, guy, sidewalk-brace, span-guy, ownership, and exclusion coding behavior.
- `JSAN_PLA_Production_Attributes.xlsx` defines 26 production point types, four production families, hierarchy, status/evidence/validation/lineage groups, and engineering measurements.

## Constraints and invariants

- Source LiDAR remains immutable; annotations are separate derived records.
- Coordinates remain in the project's declared CRS and units. No silent reprojection or unit conversion.
- Geographic coordinates are derived only from the explicitly declared project CRS. The source workbook coordinates remain immutable; verified coordinates are stored separately.
- Every mutation is authenticated, authorized, attributed to a named user, and audited.
- Only Section 3 behavior is implemented. Section 4 QC rules are outside this change.
- Catalogue-specific values not present in the supplied workbook are not invented. Such values remain explicit producer-entered attributes until an approved LUT is available.
- Existing QC workbook ingestion, PDAL conversion, synchronized views, and production startup guards remain unchanged.
- Schema rollout is additive and preserves existing SQLite/PostgreSQL data.

## Design

### Schema and API

- Add an additive `production_annotations` table with project/block identity, taxonomy, native CRS coordinates, optional reference annotation, calculated vertical/horizontal/3D measurements, Section 3 attributes as JSON, status, creator/editor, and timestamps.
- Add nullable verified-location columns to poles and geographic/linkage columns to production annotations through an additive migration.
- Add an Alembic revision that creates only the new table and indexes.
- Add authenticated catalogue and project annotation endpoints for list/create/update/delete.
- Validate point types and families against the supplied workbook taxonomy.
- Recalculate measurements server-side whenever a reference annotation is supplied.
- Audit create/update/delete actions.

### UI

- Extend the Production page with an annotation inspector and saved-point list.
- Use Potree's measuring tool for precise one-point placement on the rendered point cloud.
- Provide family/point classification, pole/item identifiers, owner/catalog/support/topology fields, status, notes, and a reference-point selector.
- Display native X/Y/Z and calculated vertical height, horizontal offset, and 3D distance.
- Require the client workbook in the Production import, list its poles in the Production inspector, display approximate versus verified coordinates, and resolve a clicked point to WGS84 through the API before save.
- Render saved annotations over the point cloud and allow edit/delete with confirmation.

## Implementation sequence

1. Add this ExecPlan and the additive model/migration.
2. Add catalogue constants, validation, measurement calculations, RBAC, CRUD APIs, and audit events.
3. Add Production annotation UI, point picking, overlay rendering, derived measurements, editing, and deletion.
4. Add API authorization/calculation/validation tests and frontend syntax/static-contract tests.
5. Run required checks and visually verify the 1920x1080 Production layout.

## Tests

- `python -m compileall api/app api/worker.py api/migrations`
- `cd api && python -m pytest -q`
- `node --check web/assets/app.js`
- `python scripts/ci/check_repo_hygiene.py`
- API cases: unauthenticated, QC wrong-role, valid create, invalid taxonomy, cross-project reference rejection, metric calculation, update, delete, and audit persistence.
- UI cases: Production tab, point type selector, pick/save/edit/delete controls, reference measurement display, and no workbook field.
- Visual check at 1920x1080 with no clipping or horizontal overflow.

## Rollout

1. Local SQLite migration and synthetic annotation tests.
2. Preview environment with non-customer COPC.
3. Staging database backup, additive migration, role verification, and representative manual point workflow.
4. Compare selected coordinates/heights against MicroStation/TerraScan before production promotion.
5. Promote the exact staging-approved commit through the normal branch flow.

## Rollback

- Roll the application image back to the previous known-good version.
- The additive table remains dormant and preserves annotations; downgrade does not drop it.
- Revert the feature through a PR. Never remove source LiDAR, annotations, or audit records as part of rollback.

## Decision log

- 2026-10-01: Store annotations separately from immutable source LiDAR.
- 2026-10-01: Store and display coordinates in native project CRS/units; do not silently transform.
- 2026-10-01: Use an optional saved annotation as the measurement reference so height, horizontal offset, and 3D distance are reproducible and auditable.
- 2026-10-01: Do not invent LUT values absent from the supplied workbook; capture the producer's explicit value and leave approved catalogue integration for a supplied LUT.
- 2026-10-01: Keep Section 4 automated QC out of this implementation as requested.
- 2026-10-02: Production—not QC—owns manual pole-location verification. GeoJSON is not required when LiDAR has an explicit correct project CRS.
- 2026-10-02: Replace Potree's `ScreenBoxSelectTool` in Production. It picks one point cloud only and throws on the combined model, which left the camera stuck in orthographic mode and blocked navigation. The replacement draws the box in plan view and always restores the camera on finish, cancel, or Esc.
- 2026-10-02: Add a MicroStation/TerraScan-style vertical section (Profile) to Production. It is frontend-only: a two-click section line plus depth defines an oriented clip box viewed orthographically from its side, with rotation locked, step/rotate/depth controls, an elevation ruler, station band, cursor elevation, and saved points labelled with height above the pole base. Coordinates stay in the native project CRS and units; no data is reprojected or stored differently.
- 2026-10-02: Production picks honour the active clip (`pickClipped`), so a profile pick cannot snap to a hidden point outside the slab. A pick that hits no LiDAR point is rejected instead of saving a draft at the origin.

## Progress

- [x] Read and visually inspect PDF Section 3 (pages 10-22).
- [x] Inspect all supplied workbook taxonomy and attribute sheets.
- [x] Create ExecPlan.
- [x] Add schema and API.
- [x] Add Production annotation UI.
- [x] Add tests and complete automated/layout verification.
- [ ] Complete coordinate and height parity acceptance with representative LiDAR in MicroStation/TerraScan.
- [x] Import Production workbook poles and persist audited verified pole coordinates.
- [x] Persist verified pole bottom/top elevations and calculated height.
- [x] Combine all Production LiDAR blocks in one viewer without physically rewriting source files.
- [x] Restore combined-model navigation (multi-cloud bounding box, Esc cancel, display-only markers, middle-drag pan, Top/Front/Side/3D views, orbit/pan modes).
- [x] Add Production vertical-section profile with pole base/top/attachment picking and height-above-base readouts.
- [ ] Compare one profile's pole base/top elevations with MicroStation/TerraScan.
