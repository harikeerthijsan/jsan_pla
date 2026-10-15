# Load resilience on Railway: separate worker, several API processes, shared throttles

## 1. Outcome
The deployed app stays responsive when many people use it at once, and LiDAR processing can't slow down or crash the website:
- The PDAL worker runs as its own Railway service.
- The API runs several processes (and can scale to several replicas).
- Overload produces a quick "busy, try again" (503) instead of a hang.

## 2. Current behavior
- Production is one Railway service, `pla-qc`: root `Dockerfile` → `api/railway_entrypoint.py`.
  - That starts `worker.py` and **one** uvicorn process in the same container, with one replica.
  - PDAL conversions share CPU and memory with every web request. An out-of-memory kill takes the whole site down.
- SQLAlchemy uses the default pool (5 + 10 overflow, 30 s timeout) per process.
  - Under a burst, requests wait up to 30 s for a connection.
- The COLLECTION Excel build (openpyxl) is CPU-heavy and runs in the request thread, with no limit on simultaneous builds.
- Two security throttles live in per-process memory:
  - failed-login lockout (`main.LOGIN_FAILURES`);
  - the email-code request limit (`email_login._REQUESTS`).
  - With more than one process or replica, each counts separately, which multiplies allowed attempts (weakens ASVS rate limiting).

## 3. Constraints / invariants
- **AGENTS #10:** production startup guards stay as they are.
- **AGENTS #2:** LiDAR keeps going browser ↔ bucket via presigned URLs, never through the API.
- **AGENTS #9:** auth behaviour (the 401 / 429 responses and their limits) must be unchanged. Tests cover lockout and the email-code limit with the shared store.
- **Safe defaults:** the default behaviour is unchanged (`PROCESS_ROLE=all`, one web process), so an existing deployment without new variables behaves as today.
- **Migrations:** they run on API and worker start under the existing Postgres advisory lock, which already serializes concurrent processes and replicas.

## 4. Design
- **Entrypoint roles:** `PROCESS_ROLE`, default `all`:
  - `web` runs uvicorn only;
  - `worker` runs `worker.py` only and has no HTTP port;
  - `all` runs both, as today.
- **Web processes:** `WEB_CONCURRENCY` (default 1) is passed to uvicorn as `--workers`.
- **Overload protection:**
  - `WEB_LIMIT_CONCURRENCY` (unset = no limit) becomes `--limit-concurrency`, which returns 503 when exceeded;
  - `--timeout-keep-alive` comes from `WEB_KEEPALIVE_SECONDS` (default 5).
- **DB pool:** `DB_POOL_SIZE` (5), `DB_MAX_OVERFLOW` (10), `DB_POOL_TIMEOUT` (15 s), `DB_POOL_RECYCLE` (1800 s). Postgres only.
- **Shared throttles:** table `auth_throttle_events (id, key, created_at)`, migration `20261014_0018`.
  - `app/throttle.py` provides `hits` / `record` / `clear`, with a sliding window in SQL and pruning of old rows.
  - Login lockout and email-code limits use it. Limits and messages are unchanged.
- **Excel build cap:** at most `WORKBOOK_BUILD_CONCURRENCY` (default 2) builds per process at once.
  - Others wait up to 20 s, then get 503 "Excel is being prepared for other users; try again in a moment".
- **IaC (`.railway/railway.ts`):** two services from the same root `Dockerfile`.
  - `pla-qc`: `PROCESS_ROLE=web`, `WEB_CONCURRENCY=2`, `WEB_LIMIT_CONCURRENCY=200`, healthcheck `/health/ready`.
  - `pla-qc-worker`: `PROCESS_ROLE=worker`, no healthcheck or domain, same database and bucket references.
  - It is applied by hand with `railway config plan/apply`, never automatically on push.

## 5. Implementation sequence
1. Shared throttle table, module, login and email-code wiring, with tests.
2. DB pool variables.
3. Entrypoint roles and uvicorn options, with tests.
4. Excel build cap, with a test.
5. `railway.ts` and docs (PRODUCTION_ENVIRONMENTS, DEPLOYMENT, RELEASE_RUNBOOK).

## 6. Tests
- `cd api && pytest -q`.
- New tests:
  - lockout after N failures, shared across fresh module state (the table is the source of truth);
  - email-code limit;
  - entrypoint command lines per role;
  - pool settings;
  - Excel cap returns 503 when full.
- `python -m compileall api/app api/worker.py`.
- Local: run with `PROCESS_ROLE=web` + `WEB_CONCURRENCY=2` and a separate `PROCESS_ROLE=worker`; sign in and process work.

## 7. Rollout
local → staging (apply IaC plan, check worker logs pick up jobs, /health/ready) → production.

## 8. Rollback
- If the new code misbehaves:
  - set `PROCESS_ROLE=all` and `WEB_CONCURRENCY=1` on `pla-qc`;
  - delete or scale down `pla-qc-worker`;
  - or roll back the deployment.
- Old code ignores the new `auth_throttle_events` table, and no data is lost.

## 9. Decision log
- **Throttles in Postgres rather than Redis:** no new service to run. Login traffic is tiny, so a small indexed table is enough.
- **Default role `all`:** a deploy before the IaC is applied keeps working exactly as now.
- **Rejected: async Excel builds via the job queue.** That would be a larger change; a per-process cap removes the stampede risk now.

## 10. Progress
- [x] 2026-10-14 Shared throttles (migration 20261014_0018, app/throttle.py; tests/test_auth_throttle.py, test_email_login.py)
- [x] 2026-10-14 DB pool settings (app/db.py pool_options; tested)
- [x] 2026-10-14 Entrypoint roles / uvicorn options (tested; live: PROCESS_ROLE=web WEB_CONCURRENCY=2 → 2 server
  processes, no worker; lockout hit at the 9th failure across both processes)
- [x] 2026-10-14 Excel build cap (503 + Retry-After when busy; tested)
- [x] 2026-10-14 railway.ts (pla-qc web + pla-qc-worker) and docs (PRODUCTION_ENVIRONMENTS, DEPLOYMENT, RELEASE_RUNBOOK)
- [ ] Staging: apply IaC plan, set secrets on pla-qc-worker, confirm the worker picks up jobs and /health/ready
- [ ] Production: same, then watch memory/CPU and Postgres connections for a day
