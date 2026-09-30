# Development Backlog

## P0 — before production pilot

- Port the remaining Sample1-specific PLA SOW rules into the portable rule engine.
- Add explicit span-guy, Other-connection, sidewalk-brace and run topology geometry.
- Extend the implemented API RBAC with OIDC/SSO after the approved JSAN identity-provider contract is supplied.
- Add a new Alembic revision for every future schema change; never return to runtime `create_all` schema evolution.
- Add explicit job cancellation and dead-letter visibility; bounded retry and stale-lease recovery are implemented.
- Add malware/content scanning required by customer policy; extension/type/size validation is implemented.
- Add storage retention policy outside the application because Railway Buckets do not currently provide lifecycle configuration.
- Validate profile corridor defaults with Delivery (width/depth/resolution) against MicroStation/TerraScan review practice.
- Add automated browser tests (Playwright) against a small non-confidential COPC fixture.

## P1 — reviewer productivity

- Linked cursor between all four views and 3D marker.
- One-click finding -> target span selection.
- Classification toggles and profile coloring by elevation/class/intensity.
- Measurement tools: delta Z, span length, attachment separation, pole height.
- Profile corridor drag/edit in Plan view.
- Split-screen revision comparison (V1 vs V2).
- Screenshot/evidence capture attached to review decision.
- Issue assignment and correction SLA.

## P2 — machine-assisted geometry QC

- Nearest-LiDAR validation of delivered pole top/base.
- Attachment-band detection and delta-Z checks.
- Conductor continuity / sag-curve candidate detection.
- Guy/anchor geometry plausibility.
- Pole lean and verticality checks.
- Configurable project/customer thresholds.

## P3 — enterprise scale

- Organization / customer tenancy.
- SSO.
- Rule-pack versioning per SOW/customer.
- Dataset revision lineage and regression reports.
- Usage telemetry and reviewer productivity analytics.
- Internal file-server ingestion agent for approved JSAN shares.
