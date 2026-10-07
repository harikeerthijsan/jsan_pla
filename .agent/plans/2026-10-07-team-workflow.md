# Team workflow: pole assignment, live "open by" indicator, admin progress dashboard, point history

## 1. Outcome
- Admins assign poles (single, list, ranges or the filtered list) to a user. Every pole row shows its assignee, and a **Mine** filter lists the signed-in person's poles.
- A pole someone currently has open shows "Open by JSAN004" in the list and in the pole header, refreshed about every 25 seconds.
- Admins open **Team progress** for a Production dataset. It shows, per user: assigned poles, poles completed (total and per day for the last 14 days), points placed and edits in the period, QC-checked poles, QC-failed poles and failure rate.
- Each saved point has a **History** view (who changed it, when, what it was), and any earlier version can be restored.

## 2. Current behavior
- No assignment or presence data. Pole status (`todo`/`progress`/`done`) is computed client-side; `done` means a base and a top point exist.
- The audit log records point create/update (with the full `before` snapshot) and delete, but nothing reads it back.
- QC findings live on the linked QC dataset (`pipeline.dataset_pair`); pole numbers map across with `normalize_pole_number`.

## 3. Constraints / invariants
- Assignments are guidance, not locks: users may still edit each other's work (an earlier product decision).
- Admins remain invisible to users. Their presence is not shown to users, and their history entries read "an admin".
- Everything is stored in the database, with nothing per process, so it works with any number of API processes.
- Additive migration only. Auth changes carry unauthorized, wrong-role and happy-path tests.
- Restoring goes through the same revision check as a normal save, so it cannot overwrite a newer edit.

## 4. Design
- Migration `20261007_0009`:
  - `pole_assignments` (project_id, pole_internal_id unique per project, user_id, assigned_by, assigned_at)
  - `pole_presence` (project_id, user_email unique per project, pole_internal_id, last_seen)
- `api/app/team.py` (APIRouter), with `hidden_authors` moved here from `main.py`:
  - `GET  /api/projects/{id}/pole-assignments` (project.read)
  - `PUT  /api/projects/{id}/pole-assignments` `{user_id|null, pole_internal_ids}` (user.manage); audit `ASSIGN_POLES`
  - `POST /api/projects/{id}/presence` `{pole_internal_id|null}` (project.read): upserts this person's row, prunes rows older than a day, returns others seen in the last 75 s (minus hidden admins)
  - `GET  /api/projects/{id}/team-progress?days=14` (work.view_all): resolves the Production/QC pair. Completion is credited to whoever saved the later of base/top. Points and edits are counted from the audit log. QC failure = any FAIL finding on the matching QC pole.
- `main.py`:
  - `GET  …/production-annotations/{aid}/history` lists audit entries with their `before` snapshots
  - `POST …/production-annotations/{aid}/restore` `{audit_id, expected_revision}` re-applies a snapshot through the shared update path, audited as `RESTORE_PRODUCTION_ANNOTATION`
- Frontend:
  - pole-row chips (assignee, open-by) and the **Mine** filter
  - admin **Assign** dialog (tokens: internal_id, `a-b` ranges, Pole Numbers, or "all poles in the current list")
  - presence heartbeat while Production is open (paused when the tab is hidden)
  - admin **Team progress** page
  - **History** panel in the point editor

## 5. Implementation sequence
Migration/models → team.py API → history/restore API → tests → frontend → browser check.

## 6. Tests
`pytest -q` with `tests/test_team_workflow.py`: assignment auth/validation, Mine data, presence visibility and expiry, dashboard numbers on a fixture, history listing, and restore (including a stale-revision refusal and admin masking).

## 7. Rollout
Staging, then production. No new variables.

## 8. Rollback
Redeploy the previous release. The new tables are ignored by older code.

## 9. Decision log
- Heartbeat polling (25 s) instead of WebSockets: works behind Railway's proxy and with several API processes, with no new infrastructure.
- Restore covers earlier versions of existing points. Re-creating deleted points is excluded because numbered groups (anc_2, …) may have been renumbered since.
- Days are UTC calendar days.

## 10. Progress
- [x] 2026-10-07 implemented: migration 0009, `team.py` (assignments, presence, team-progress), point history/restore, frontend (chips, Mine, Assign dialog, presence heartbeat, Team progress page, History panel).
- [x] 2026-10-07 fixed a completion-credit tie: timestamps can tie at clock resolution, so the creation audit row id breaks ties in true save order (found as an intermittent test failure).
- [x] 2026-10-07 pytest 135 passed ×3. Browser walkthrough on sample2: 16/16.
