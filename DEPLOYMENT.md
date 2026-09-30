# Railway deployment

The repository is packaged as one public Railway application service plus two
managed resources:

- `pla-qc`: the static web UI, FastAPI API, and PDAL background worker
- `Postgres`: durable application data
- `pla-files`: private Railway object storage for workbooks, LAS/LAZ/COPC, and
  generated profile data

The root `Dockerfile` is the deployable image. It listens on Railway's `PORT`,
serves the UI and API on the same origin, waits for PostgreSQL during startup,
starts the background worker, and exposes `/health/live` and `/health/ready`
for deployment checks (`/health` is kept for existing monitors).

## Recommended CLI deployment

Install the current Railway CLI, then authenticate:

```powershell
npm install -g @railway/cli
railway login
```

From the repository root, create/link a Railway project and apply the included
Infrastructure as Code definition:

```powershell
railway init
railway config plan
railway config apply
```

The configuration in `.railway/railway.ts` provisions the app service,
PostgreSQL, and a Singapore-region storage bucket. Review the plan before
applying it, especially if you are applying it to an existing project.

Set the required secrets on the `pla-qc` service before its first deployment:

```powershell
railway variable set --service pla-qc ADMIN_EMAIL=admin@example.com ADMIN_PASSWORD="use-a-unique-password" JWT_SECRET="use-at-least-32-random-characters"
```

Deploy the repository and generate its public domain:

```powershell
railway up --service pla-qc
railway domain --service pla-qc
```

If the generated domain was added after the first deployment, redeploy once so
`RAILWAY_PUBLIC_DOMAIN` is present in the running container:

```powershell
railway redeploy --service pla-qc
```

## Dashboard deployment

You can deploy the same package without the IaC file:

1. Create a Railway project, a PostgreSQL database, and a Storage Bucket.
2. Create a service from this GitHub repository. Keep the root directory at the
   repository root; Railway will detect the root `Dockerfile`.
3. Generate a public domain and configure `/health/ready` as the healthcheck path.
4. Add the variables below using Railway reference variables.
5. Keep the service at one replica and deploy.

```text
APP_ENV=production
DATABASE_URL=${{Postgres.DATABASE_URL}}
ADMIN_EMAIL=<company administrator email>
ADMIN_PASSWORD=<unique password, at least 12 characters>
JWT_SECRET=<random secret, at least 32 characters>
STORAGE_MODE=s3
BUCKET=${{pla-files.BUCKET}}
BUCKET_ENDPOINT=${{pla-files.ENDPOINT}}
BUCKET_ACCESS_KEY_ID=${{pla-files.ACCESS_KEY_ID}}
BUCKET_SECRET_ACCESS_KEY=${{pla-files.SECRET_ACCESS_KEY}}
BUCKET_REGION=${{pla-files.REGION}}
S3_ADDRESSING_STYLE=virtual
AUTO_CONFIGURE_BUCKET_CORS=true
BUCKET_CORS_ORIGINS=*
SEED_DEMO=false
WORKER_POLL_SECONDS=3
DB_CONNECT_TIMEOUT=120
```

If you choose different resource names, change `Postgres` and `pla-files` in
the reference expressions to match the names on your Railway canvas.

## Bucket CORS

At startup, the API applies a bucket CORS policy that permits browser uploads,
multipart `ETag` access, COPC range reads, and profile downloads. The packaged
default is `BUCKET_CORS_ORIGINS=*`; access to objects still requires a temporary
signed URL. To restrict browser origins, replace it with a comma-separated list:

```text
BUCKET_CORS_ORIGINS=https://your-app.up.railway.app,https://qc.example.com
```

Redeploy after changing this value so the policy is reapplied.

## Validation

After deployment, verify the health endpoint:

```powershell
Invoke-RestMethod "https://your-app.up.railway.app/health/ready"
```

Expected fields include `status: ready`, `app_env: production`, version
`3.3.0-industry`, `storage_mode: s3` and `checks` all `ok`. Staging, CI gates and
rollback are described in `docs/RELEASE_RUNBOOK.md`. Then open the domain, sign
in with the configured admin credentials, and run one real workbook plus
LAS/LAZ/COPC upload.

## Operational notes

- Keep the app at one replica. The bundled API and worker share a database job
  queue that is intentionally packaged for a single service replica.
- LiDAR conversion uses ephemeral scratch disk. The plan must provide enough
  temporary disk for a source block and its generated COPC at the same time.
- Uploaded and generated files are durable in the bucket; scratch files are
  deleted after each job.
- The app creates its current schema at startup. Introduce Alembic migrations
  before making schema changes against an established production database.
- Set Railway usage limits and back up PostgreSQL before a customer pilot.
