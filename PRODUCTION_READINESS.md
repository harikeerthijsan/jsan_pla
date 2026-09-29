# Production readiness - Railway package

## Deployment target

- Public app: one Railway service built from the root `Dockerfile`
- Database: Railway PostgreSQL over its private connection URL
- LiDAR/object storage: private Railway Storage Bucket using presigned URLs
- Runtime: FastAPI web/API plus the PDAL processing worker in one container

The frontend uses the application origin automatically, so no separate Vercel
deployment or frontend API URL rewrite is required.

## Required production variables

The complete list is in `.env.railway.example`. Startup fails clearly when any
required database, administrator, signing-secret, or bucket variable is
missing, when the JWT secret is shorter than 32 characters, or when the
administrator password is unsafe.

## Pilot gate

1. Apply and review `.railway/railway.ts`, or create equivalent resources in
   the dashboard.
2. Confirm `GET /health` reports `status=ok` and `storage_mode=s3`.
3. Sign in with the production administrator account.
4. Upload one real workbook and LiDAR block and confirm direct/multipart bucket
   upload succeeds.
5. Confirm LAS/LAZ to COPC conversion completes in the worker logs.
6. Open a pole-to-pole profile and compare it with the delivery team's
   MicroStation/TerraScan result.
7. Confirm the Railway plan has sufficient RAM and ephemeral scratch disk for
   the largest LiDAR block.
8. Configure usage limits, PostgreSQL backups, and the customer retention
   policy before loading customer data.

## Scaling constraint

Keep `pla-qc` at one replica. Multiple replicas can claim the same queued job
because this version does not yet use an atomic database claim or external job
broker. Split the worker into its own service and add robust job claiming before
horizontal scaling.
