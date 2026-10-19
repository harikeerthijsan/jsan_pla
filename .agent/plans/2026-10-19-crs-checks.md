# Source CRS: detect, check and correct (no silent conversions)

## 1. Outcome
Importing a dataset with the wrong Source CRS can no longer misplace poles and GeoJSON silently.

**Background.** `D:\PLA1_Sample2` is EPSG:6426 (California zone 6 ftUS) in every file: LiDAR headers, GeoJSON `crs`, and Excel lat/lon (0 ft offset). It was imported with the dialog's default, EPSG:6424 (zone 5), and the poles landed about 723,000 ft (~137 miles) from the LiDAR.

1. **Check:** a GeoJSON or LiDAR whose CRS differs from the Source CRS stops the import with a clear message.
   - In the import dialog, before any upload.
   - On the server at the start of processing, before any conversion.
   - In the GeoJSON import.
2. **Fill in:** the dialog pre-fills Source CRS from the GeoJSON's `crs` and the LiDAR header, unless the user typed a value.
3. **Correct:** an admin can change the CRS of an existing dataset.
   - Saved points' latitude/longitude and the poles' verified lat/lon are recomputed from their X/Y.
   - A re-import of poles and GeoJSON is queued. Converted LiDAR is reused, and the new CRS is checked against the LiDAR headers first.

## 2. Current behavior
- `to_copc` stamps the project CRS only on LiDAR files that have none; it never reprojects. So LiDAR stays in its own CRS.
- `parse_workbook` converts each pole's lat/lon into the project CRS, so the pole lands wherever the project CRS puts it.
- `geojson_import` transforms from the GeoJSON's declared CRS into the project CRS. With a wrong project CRS, the pins are shifted between zones.

## 3. Constraints / invariants
- **AGENTS #7:** no silent CRS conversion.
  - A projected GeoJSON in a different CRS from the dataset is refused instead of being transformed. Geographic (WGS84 / CRS84) GeoJSON is still transformed, as it always has to be.
  - A CRS change is explicit, needs an admin, and is audited (`CHANGE_PROJECT_CRS`, from/to).
- **AGENTS #2:** LiDAR checks read only the header. The browser reads a `File.slice`; the server does a ranged read (local file, or S3 `Range`), so nothing large is proxied or downloaded.
- **AGENTS #9:** the CRS endpoint is tested signed out (401), with the wrong role (403), and on the happy path.

## 4. Design
- **`app/crs_check.py`:**
  - `las_epsg(header_bytes)` reads the horizontal EPSG from the LAS/LAZ/COPC VLRs: WKT (record 2112) or GeoKeys (34735, ProjectedCSType 3072).
  - `object_lidar_epsg(key)` does a ranged read of the header and parses it.
  - `crs_epsg(text)` normalises a CRS string to its EPSG code.
  - `crs_name(code)` gives the human-readable name.
- **`storage.read_range(key, start, length)`** for partial reads.
- **Processor:** before conversion, every LiDAR source file's EPSG is compared with the project CRS. A mismatch fails the job with an actionable message, and nothing is converted.
- **`PUT /api/projects/{id}/crs {crs}`** (`project.create`).
  - It refuses (409) while a job is running.
  - It refuses (422) when the CRS contradicts the LiDAR headers or the GeoJSON's declared projected CRS.
  - Otherwise it saves the CRS, recomputes lat/lon, and queues `LIDAR_INGEST`.
- **Dialog:**
  - A CRS note under Source CRS shows what was detected, with the auto-fill.
  - Mismatches block the submit.
- **Header:** admins get a "Change CRS" control.

## 5. Tests
`cd api && pytest -q`. New `tests/test_crs_checks.py` covers:
- header parsing (WKT, GeoKeys, real file);
- the processor guard;
- the GeoJSON refusal;
- the endpoint: auth, contradiction refusal, recompute, job queued.

## 6. Rollout / rollback
- **Rollout:** no schema change.
- **Rollback:** redeploy the previous release. Datasets keep their CRS values.

## 7. Progress
- [x] 2026-10-19 Backend checks + endpoint + tests (tests/test_crs_checks.py; full suite 334 passed, only the unrelated outputs/ hygiene check fails)
- [x] 2026-10-19 Dialog + header UI. Browser check with D:\PLA1_Sample2: GeoJSON fills EPSG:6426, the LiDAR headers confirm it,
  typing EPSG:6424 is flagged and blocks the upload (no dataset created).
  Found while testing: the tiles' WKT names the projection without an EPSG id, and a browser-side regex picked the datum's
  id (6318). The WKT is now identified on the server (`POST /api/crs/identify`, the same pyproj check as processing).
