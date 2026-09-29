# Codex ExecPlans for PLA QC

Use an ExecPlan for work expected to touch multiple subsystems, take more than roughly one focused coding session, alter database shape, change auth/RBAC, or change production deployment architecture.

An ExecPlan must be self-contained and updated while work progresses. Put active plans under `.agent/plans/`.

Each plan must contain:
1. **Outcome** — observable user/business result.
2. **Current behavior** — what exists now and relevant files.
3. **Constraints/invariants** — especially data safety, CRS, upload, and auth constraints.
4. **Design** — API/schema/UI/worker changes and why.
5. **Implementation sequence** — small checkpoints that keep the app runnable.
6. **Tests** — exact commands and scenarios.
7. **Rollout** — local → preview → staging → production.
8. **Rollback** — how to return to the previous known-good release without losing customer data.
9. **Decision log** — important design decisions and alternatives rejected.
10. **Progress** — checklist with timestamps or commit references when available.

Never put secrets or customer data in a plan.
