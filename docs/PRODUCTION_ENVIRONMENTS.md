# Industry-grade environment strategy

## Environment model

| Layer | Local | PR/Preview | Staging | Production |
|---|---|---|---|---|
| Purpose | Developer iteration | Isolated code review | Production-like acceptance | Live operations |
| Data | Synthetic/sample | Synthetic/sanitized | Sanitized or approved staging set | Customer production data |
| Database | SQLite allowed | Isolated ephemeral Postgres | Isolated persistent Postgres | Isolated persistent Postgres |
| Object storage | Local disk allowed | Isolated bucket | Isolated bucket | Isolated private bucket |
| API | localhost | temporary | staging API | production API |
| Frontend | localhost | protected preview | staging domain | production domain |
| Secrets | local `.env` ignored by Git | preview-scoped | staging-scoped | production-scoped sensitive secrets |

Staging and production must never share PostgreSQL credentials, buckets, JWT secrets, or admin accounts.

## Recommended topology

### Railway
Topology (`.railway/railway.ts`): one Railway project with two services built from the root `Dockerfile`, plus
`Postgres` and bucket `pla-files`:

- `pla-qc` (`PROCESS_ROLE=web`): UI + API, public domain, healthcheck `/health/ready`.
- `pla-qc-worker` (`PROCESS_ROLE=worker`): the PDAL worker only, no domain or healthcheck.

LiDAR conversions therefore never share CPU or memory with web requests. An existing single-service deployment
without `PROCESS_ROLE` keeps running both in one container (`all`, the default). `api/Dockerfile`,
`railway-api.json` and `railway-worker.json` are not what production builds.

### Capacity under load

| Variable (service) | Default | Purpose |
|---|---|---|
| `PROCESS_ROLE` (both) | `all` | `web`, `worker` or `all` (both in one container). |
| `WEB_CONCURRENCY` (pla-qc) | `1` (IaC: `2`) | uvicorn processes per replica. Each uses roughly 250–400 MB. |
| `WEB_LIMIT_CONCURRENCY` (pla-qc) | unset (IaC: `200`) | Open requests per process before it answers 503 at once instead of hanging. |
| `WEB_KEEPALIVE_SECONDS` (pla-qc) | `5` | Idle keep-alive per connection. |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` | `5` / `10` / `15` s | Postgres pool per process. |
| `WORKBOOK_BUILD_CONCURRENCY` (pla-qc) | `2` | COLLECTION Excel builds at once per process; others wait up to 20 s, then get 503. |

Keep `replicas x WEB_CONCURRENCY x (DB_POOL_SIZE + DB_MAX_OVERFLOW)` plus the worker's pool under the Postgres connection
limit (Railway default: 100). Sign-in throttles (failed logins, email-code requests) are stored in Postgres
(`auth_throttle_events`), so limits hold across processes and replicas. Raise the `pla-qc` replica count for more
traffic. Keep `pla-qc-worker` at one replica unless processing queues build up, since job claims are atomic.

Maintain two persistent Railway environments in the same project: `production` and `staging`. Each has
its **own** `Postgres` and `pla-files` instances; variables use reference syntax (`${{Postgres.DATABASE_URL}}`,
`${{pla-files.BUCKET}}`), which resolves inside the environment being deployed, so staging cannot
reach production data unless someone pastes literal production credentials (never do this).
PR environments, if enabled, must use **staging** as their base environment.

| Setting | staging | production |
|---|---|---|
| Git branch (autodeploy) | `staging` | `main` |
| Wait for CI | on | on |
| `APP_ENV` | `staging` (from `ctx.environment`) | `production` |
| Healthcheck | `/health/ready` | `/health/ready` |
| Postgres / bucket | staging-only | production-only |
| `JWT_SECRET`, `ADMIN_*` | staging-only values | production-only values |
| Data | sanitized / approved staging set | customer production data |

- Expose only the public app domain; database and bucket stay private (bucket objects via presigned URLs).
- Use Railway private networking for app↔database traffic.
- Healthcheck is `/health/ready` (DB `SELECT 1` + storage configuration). `/health/live` is process-only.
- If the production environment is not named `production`, set `PRODUCTION_RAILWAY_ENVIRONMENT` to its name;
  the API compares `APP_ENV` with Railway's `RAILWAY_ENVIRONMENT_NAME` and refuses a mismatch.
- Store LAS/LAZ/COPC in the private S3-compatible bucket, not on ephemeral service disks.
- Use presigned URLs for browser uploads/downloads so large LiDAR does not traverse the API process.
- Bucket CORS must list explicit browser origins. When `BUCKET_CORS_ORIGINS` is unset, the app derives
  `https://$RAILWAY_PUBLIC_DOMAIN`; set `BUCKET_CORS_ORIGINS` explicitly when a custom/Vercel domain is used.
  Staging and production reject wildcard or missing origins while automatic bucket CORS is enabled.

### Database migrations

API and worker startup execute `alembic upgrade head` through `app.db.initialize_schema()`. A PostgreSQL
transaction advisory lock serializes migration startup across the combined API/worker process and rolling
replicas. The initial v3.4 revision adopts databases previously initialized with `create_all` and creates only
missing tables; it does not drop or rewrite customer data. Future schema changes require a new Alembic revision.

### Vercel
Use Preview for pull requests and Production for the live frontend. If the team uses Vercel Pro, create one persistent custom `staging` environment with staging-only API configuration. Protect non-production deployments and keep production variables separate.

## Branch/release flow

`feature/*` → PR/Preview → `staging` → staging acceptance → `main` → production.

Required gates before production:
1. CI green.
2. API `/health/ready` green in staging.
3. Upload/process a representative workbook + LAS/LAZ in staging.
4. Validate one Plan/Profile/Cross/3D case against MicroStation/TerraScan.
5. Confirm role/access behavior.
6. Confirm staging storage/database are not production resources.
7. Promote the exact reviewed commit.

## Runtime safety
`app.main.validate_runtime_environment()` runs at startup when `APP_ENV` is `production` or `staging` and
refuses to start with SQLite, non-`s3` storage, missing/default/short `JWT_SECRET` (<32) or `ADMIN_PASSWORD`
(<12), wildcard `CORS_ORIGINS`, `SEED_DEMO=true`, or an `APP_ENV` that disagrees with the Railway
environment. `railway_entrypoint.py` additionally requires the bucket variables. An unset `CORS_ORIGINS` is
allowed because the Railway image serves UI and API from one origin; set an explicit list only for a
cross-origin frontend. Do not disable these guards; correct the environment instead.

## Staff accounts
When `STAFF_INITIAL_PASSWORD` is set, every API start creates any missing account among `Admin001`–`Admin002`
(role ADMIN) and `JSAN001`–`JSAN020` (role USER) with that password. Existing accounts are never changed, so
rotating the variable only affects accounts created later. Each account must choose its own password at first
sign-in; until then every API except the profile endpoints returns 403 `password_change_required`. The guard
rejects a configured value shorter than 12 characters or equal to a known default. Use a different value in each
environment. Only ADMIN uploads LiDAR/Excel/GeoJSON or creates datasets, sees every user's Production work, and
edits a workbook `internal_id`. USER accounts share Production work with each other but never see an admin's.

## Office-network access
Admins can limit USER accounts to office networks in Profile → **Network access** (stored in the database, so no
redeploy is needed). Admins are never restricted, and individual users can be given "Anywhere" access in the users
table. The restriction starts off and cannot be turned on with no networks listed.

Behind Railway the client address is taken from the edge proxy's `X-Real-IP` header (`CLIENT_IP_HEADER` overrides
the header name elsewhere; locally the socket address is used). Railway sees an office's **public** address, never a
LAN address such as 192.168.3.100, so private ranges are rejected there: open the card from the office and use
**Add my current network**. Turning the switch off restores access immediately. Every change and every blocked
sign-in is audited.

## CI isolation
GitHub Actions uses no repository secrets and no `pull_request_target`. CI runs with SQLite and local
storage only, so a PR can never reach staging or production databases/buckets. Deployment is performed
by Railway's GitHub integration (Wait for CI), so no provider token exists in GitHub.

## Backups / recovery
- Define PostgreSQL backup/restore ownership and test restoration periodically.
- Source uploads are immutable; derived COPC/profile artifacts can be rebuilt.
- Record the deployed application version and processing version with each dataset revision.
- Keep rollback instructions in `docs/RELEASE_RUNBOOK.md`.
