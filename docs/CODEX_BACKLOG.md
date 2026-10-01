# Codex production backlog

Priority order for parallel Codex workstreams:

1. **Enterprise authentication/RBAC** — named users, OIDC/SSO, MFA delegated to IdP, endpoint-level role guards.
2. **Delivery + QC linked workspaces** — one dataset, two role-based operational surfaces; no duplicate upload/processing.
3. **Dataset versioning and correction loop** — v1/v2/v3, correction requests, resubmission, resolved/new/still-open comparison.
4. **Database migrations** — Alembic baseline is implemented; every future schema change must add a revision.
5. **Queue reliability** — atomic job claiming, lease/heartbeat, retry policy, idempotency, dead-letter visibility.
6. **Observability** — structured logs, request IDs, job IDs, error reporting, processing duration/point-count metrics.
7. **Profile parity** — evidence validator/comparator is implemented; approved reference datasets and tolerances remain a Delivery/customer gate.
8. **Rule coverage** — complete the remaining PLA SOW rules and version the rule set.
9. **Backup/restore drill** — documented Postgres restore and object-storage recovery/rebuild process.
10. **Performance** — cache profile results, benchmark COPC range requests and concurrent reviewers.
