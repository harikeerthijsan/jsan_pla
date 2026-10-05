# Production client GeoJSON overlay

## Outcome

A producer can attach the client's pole GeoJSON when importing a Production dataset. Each GeoJSON pole is matched to its workbook pole, drawn over the combined LiDAR model, and clicking it in the 3D view shows the GeoJSON properties next to the workbook values, the LiDAR-verified location and elevations, and the offsets between them.

## Current behavior

- Production import accepts one `.xlsx` workbook (`WORKBOOK`) and LAS/LAZ/COPC files (`LIDAR_SOURCE`). Any other role is rejected by `validate_upload_request`.
- The `LIDAR_INGEST` job converts LiDAR and imports workbook poles; nothing reads GeoJSON.
- The import dialog states "GeoJSON is not required".

## Constraints and invariants

- GeoJSON is optional. Workbook and LiDAR remain required.
- The uploaded GeoJSON is immutable source; parsed features are a separate derived table.
- No silent CRS conversion. RFC 7946 GeoJSON is WGS84 longitude/latitude. A legacy `crs` member naming an EPSG code or CRS84 is honoured. The source CRS, project CRS and transformed coordinates are all stored, and the import is audited.
- Treat the file as untrusted: extension, size, JSON structure, geometry types, feature count and finite coordinates are validated. Properties are rendered as text only.
- A rejected GeoJSON does not discard converted LiDAR. The job succeeds, the rejection is surfaced to the user in the job message, and it is audited.
- Schema change is additive (new table only) and preserves SQLite/PostgreSQL data.

## Design

### Schema

`production_geo_features` (migration `20261002_0005`): project, source file, feature index, geometry type, source CRS, source geometry, projected geometry, representative projected X/Y, properties, matched pole internal ID, match method (`ID` or `NEAREST`), match property and match distance.

### Import (`api/app/geojson_import.py`)

1. Parse a `FeatureCollection` (or single `Feature`). Allowed geometries: Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon. Limit 200,000 features.
2. Resolve the source CRS, transform every coordinate to the project CRS with pyproj (`always_xy`), and validate geographic ranges.
3. ID matching: try every property key against workbook `pole_number` and `internal_id` (normalised text, `12.0` == `12`). The key/target pair with the most matches wins.
4. Point features without an ID match fall back to the nearest workbook pole within 10 ft (3 m for metric projects), using the LiDAR-verified X/Y when present, otherwise the workbook latitude/longitude transformed to the project CRS. Lines and polygons are stored but not matched.
5. Re-import replaces the project's derived features.

### API

- `GEOJSON` upload role: `.geojson`/`.json`, `MAX_GEOJSON_BYTES` (default 50 MB).
- `GET /api/projects/{id}/production-geo-features` (`project.read`): features with projected geometry, properties, match details, and offsets to the workbook and LiDAR-verified locations of the matched pole.

### UI

- Optional "Client pole GeoJSON" input in the Production import; validated in the browser before upload.
- Point features drawn as vertical pins: verified base→top, else workbook bottom→top, else the containing LiDAR block's Z range. Lines and polygons drawn as outlines at the project's reference ground elevation (median known pole base). Colour shows match method.
- Clicking near a pin (screen-space) opens a details card: GeoJSON properties, match, workbook pole, verified values, offsets. "Use this pole" selects it in the attribute form; "Zoom" centres the view.
- GeoJSON toggle in the view toolbar; catalogue row summarising feature and match counts.

## Tests

- Unit: WGS84→EPSG:6424 transform parity with pyproj, legacy `crs` member, ID match (text and numeric), nearest fallback and tolerance, unmatched, non-point storage, invalid JSON/type/geometry/coordinates.
- API: `GEOJSON` upload role accepted and validated, wrong role (QC reviewer) cannot upload, endpoint unauthenticated 401 and happy path.
- Migration head and table presence.
- Frontend static contract and a browser run on a generated GeoJSON.

## Rollout and rollback

Additive migration; roll the application back to the previous image if needed. The table remains dormant; downgrade does not drop it.

## Decision log

- 2026-10-02: Parse GeoJSON on the server during the existing LiDAR ingest job so the CRS transform and matching are validated once and audited (browser parsing rejected: unaudited transform, repeated work).
- 2026-10-02: Auto-detect the ID property instead of a fixed field name, because client exports name it differently; the chosen property is stored per feature.
- 2026-10-02: A bad GeoJSON is reported, not fatal, so hours of LiDAR conversion are not discarded.
- 2026-10-02: Attaching a GeoJSON to an existing dataset and editing GeoJSON properties are out of scope.

## Progress

- [x] ExecPlan.
- [x] Schema, migration, import module, worker step, API.
- [x] Upload, overlay, click details UI.
- [x] Tests and verification: 98 API tests; browser run on sample2 LiDAR with a synthetic GeoJSON (ID, offset ID, nearest and unmatched poles, a span line), including profile view and browser-side rejection of an invalid file; QC four-view layout unchanged.
- [x] Keep the uploaded client GeoJSON identifiable as immutable source in the Production catalogue; annotation exports are generated separately from saved Production points.
- [ ] Import a real client GeoJSON through the full upload/worker path on staging and confirm the detected ID property and offsets with the client.
