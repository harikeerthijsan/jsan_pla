# Deployment Options — PLA Quality Validation Workbench v3.3

## Option A — Minimum-cost internal pilot (recommended for validation)

- Frontend: Cloudflare Pages/Workers static hosting (static asset requests are free on Pages; Workers Free can support small dynamic needs).
- API + PostgreSQL + worker: Railway Hobby.
- LiDAR/COPC: Railway Storage Bucket or Cloudflare R2.
- Keep direct browser-to-object-storage uploads and COPC range reads; do not proxy LiDAR through the API.
- Enable Railway Serverless on the API when compatible. Keep the PDAL worker available only when processing is required; a polling worker should not be expected to sleep reliably.
- Set Railway hard usage limits and per-service CPU/RAM limits.

This is the lowest-cost practical cloud pilot. Railway Hobby has a $5 monthly minimum that counts toward resource usage. Railway object storage is $0.015/GB-month with free bucket operations and bucket egress.

## Option B — Simplest vendor footprint

- Serve the static web UI from the Railway API/container.
- Railway API + worker + PostgreSQL + Bucket.
- One platform to operate and one bill.
- Trade-off: frontend traffic uses Railway service egress instead of a dedicated edge CDN, and frontend/backend releases are more tightly coupled.

Best for small internal reviewer teams where simplicity matters more than global edge performance.

## Option C — JSAN production default

- Frontend: Vercel Pro.
- Backend: Railway Pro.
- Database: Railway PostgreSQL over private networking.
- LiDAR: Railway Storage Bucket or Cloudflare R2.
- Custom domains: `qc.jsanconsulting.com` and `api-qc.jsanconsulting.com`.
- Separate staging and production environments.

Vercel Hobby is personal/non-commercial only; JSAN production should use Pro if Vercel is selected. Railway Pro provides the stronger availability target, longer logs and team-scale controls expected for production.

## Option D — Cost-optimized commercial frontend

- Frontend: Cloudflare Pages/Workers.
- API/worker/database: Railway Pro or Hobby during pilot.
- LiDAR: Cloudflare R2.

Static Pages requests are free; R2 standard storage is $0.015/GB-month and Internet egress is free. This is attractive where COPC read traffic may become significant.

## LiDAR processing principles

1. Upload source LAS/LAZ directly to object storage with presigned URLs.
2. Process one LiDAR block at a time to bound ephemeral-disk and RAM pressure.
3. Worker downloads only the block it is processing.
4. Generate COPC and upload it to object storage.
5. Browser reads COPC directly using HTTP range requests.
6. Delete worker scratch files immediately after a successful upload.
7. Retain source LAS/LAZ according to customer retention policy; if source retention is not required in the cloud, archive or remove it after COPC verification.

## Cost controls

- Railway compute is usage based; configure hard monthly usage limits and per-service replica limits.
- Railway service egress is billed, but Storage Bucket egress is free. Direct client uploads avoid API egress.
- Railway Storage Bucket: $0.015/GB-month; operations and bucket egress are free.
- Cloudflare R2 Standard: $0.015/GB-month, a 10 GB monthly free storage tier, operation charges after the included quotas, and free Internet egress.
- Use private Railway networking between API/worker and PostgreSQL.
- Do not keep a high-memory PDAL worker running at full utilization when there are no jobs.

## Production factors beyond cost

- Authentication: replace local development credentials; use strong JWT secrets and preferably enterprise SSO later.
- Data isolation: namespace every object and database record by organization/project/delivery version.
- Audit: retain reviewer decisions, overrides, comments, rule version and delivery version.
- Backups: database backups plus object-storage retention policy.
- Security: private buckets, short-lived presigned URLs, restrictive CORS and no public raw source objects.
- Observability: API/worker structured logs, job duration, PDAL failures, queue depth, upload failures and viewer-load telemetry.
- Browser performance: load only the selected pole/span COPC blocks; never fit every project block by default.
- Reviewer ergonomics: synchronized Plan/Profile/Cross/3D views, individual maximize/minimize controls and focus-workspace mode.
