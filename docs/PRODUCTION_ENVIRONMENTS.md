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
Use one Railway project with services `api`, `worker`, `postgres`, and `lidar-bucket`. Maintain persistent `staging` and `production` environments. PR environments may be enabled from staging for backend/integration previews.

- Expose only the public API when needed; worker/database remain private.
- Use Railway private networking for API↔database/worker-adjacent service traffic.
- Configure API healthcheck as `/health/ready`.
- Store LAS/LAZ/COPC in the private S3-compatible bucket, not on ephemeral service disks.
- Use presigned URLs for browser uploads/downloads so large LiDAR does not traverse the API process.

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
Production API refuses to start when configured with SQLite, local storage, weak/default JWT/admin credentials, wildcard/empty CORS, or demo seeding. Do not disable this guard; correct the environment instead.

## Backups / recovery
- Define PostgreSQL backup/restore ownership and test restoration periodically.
- Source uploads are immutable; derived COPC/profile artifacts can be rebuilt.
- Record the deployed application version and processing version with each dataset revision.
- Keep rollback instructions in `docs/RELEASE_RUNBOOK.md`.
