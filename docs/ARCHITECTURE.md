# Architecture — v3 Profile

## Runtime

```text
Vercel web client
    |
    | JSON / auth / QC
    v
Railway FastAPI ---------------- PostgreSQL
    |
    | queue jobs
    v
Railway Worker (Python + PDAL)
    |
    +--- source LAS/LAZ -> COPC
    +--- workbook -> features / QC
    +--- on-demand profile / cross-section extraction
    |
    v
Railway Bucket or S3-compatible object storage
    - source workbook
    - source LAS/LAZ
    - processed COPC
    - cached section JSON
```

Large LiDAR files are not proxied through Vercel. The browser receives a temporary object URL for COPC and Potree streams the 3D data directly. Small profile/cross-section JSON products are returned through the API.

## Engineering frame

For primary pole `A` and target pole `B`:

```text
ux = normalize(B.xy - A.xy)
uy = perpendicular(ux)

station = dot(P.xy - A.xy, ux)
offset  = dot(P.xy - A.xy, uy)
elevation = P.z
```

Views:

- Plan: `(station, offset)`
- Longitudinal profile: `(station, elevation)`
- Cross section: `(offset, elevation)` for points near the current station
- 3D: original project coordinates

The cross-section station can move along the span without regenerating LiDAR because it filters the already extracted corridor sample.

## Section worker

The worker selects only the COPC blocks mapped to the primary/target poles. PDAL `readers.copc` receives:

- a spatial `bounds` window
- a requested `resolution`

The worker then applies the rotated corridor filter in the JSAN span coordinate frame and stores a capped sample in object storage. The result key is deterministic for project, poles, width, depth, resolution and maximum point count, so repeat reviews use the cache.

## Why not Potree native profile

Potree remains the 3D renderer. The 2D engineering profiles are JSAN-owned views driven by PDAL-generated data. This avoids coupling core QC to the native Potree height-profile implementation and makes Plan/Profile/Cross synchronized with delivery geometry and rule evidence.
