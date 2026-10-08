# Super admin role and oversight page

## 1. Outcome
A new **Super admin** role:
- Sees everyone's work: an activity feed, a per-person summary, and Team progress across all datasets.
- Creates admins and users.
- Decides whether each admin or user works only from the office networks or from anywhere.

Super admins' own work is invisible to admins and users. Only another super admin can see it.

## 2. Current behavior
- `api/app/rbac.py`: `ADMIN` has `user.manage` + `work.view_all`. Any admin can create or edit any account, including other admins.
- `api/app/network_access.py`: `user_network_allowed` always lets `ADMIN` in. Only users have the per-person `remote_access` switch.
- `api/app/team.py`:
  - `hidden_authors` hides admins' work from users. Admins see everything.
  - `team_progress` covers one Production dataset and lists every author.
- `api/app/notifications.py`: actors who are admins are shown to users as "an admin".
- `web/assets/modules/profile.js`: admin account table. Access toggle for users only, and the create form offers Admin/User.

## 3. Constraints / invariants
- AGENTS #9: tests for unauthorized, wrong-role (admin, user) and happy path on every new or changed endpoint.
- AGENTS #10: no weakening of production startup guards.
- No one can make themselves super admin from inside the app. The first super admin comes from server configuration.
- Upgrading must lock nobody out. Existing admins keep "anywhere" until a super admin changes it.
- The last active super admin cannot be deactivated or demoted.
- Additive migration only; existing SQLite databases keep working.

## 4. Design
**Role.** `SUPER_ADMIN` = all `ADMIN` permissions + `user.manage_admins` + `super.view`.

**Bootstrap.**
- `SUPER_ADMIN_EMAILS` (comma list of e-mails or usernames) promotes those existing accounts at startup.
- Each promotion is audited (`PROMOTE_SUPER_ADMIN`, actor `system`).
- After that, a super admin can promote others in the page.

**Visibility (`hidden_authors`).**
- Super admin → nothing is hidden.
- Admin → super admins' work is hidden.
- User → admins' and super admins' work is hidden.

The same rule applies to:
- the account list: admins never see super-admin accounts, and a super admin is a 404 to an admin
- Team progress rows, point history, presence
- notifications: a super admin actor is shown as "an admin" to non-super recipients

**Account management.**
- Creating, editing, (re)activating, resetting or changing the access of an `ADMIN`/`SUPER_ADMIN` account, or assigning those roles, needs `user.manage_admins`. Otherwise → 403.
- Admins keep full control of user accounts.

**Network access.**
- `SUPER_ADMIN` is always allowed.
- `ADMIN` now follows `remote_access` like users.
- Migration `20261008_0013` sets `remote_access = true` for existing admins.
- New admin accounts default to anywhere.

**New API** (`api/app/super_admin.py`, all `super.view`):
- `GET /api/super/people?days=` — every account with role, access, sign-in, work counts (points created, edits, deletions, QC decisions, poles completed) and last active.
- `GET /api/super/activity?actor=&group=&project_id=&before_id=&limit=` — audit timeline, newest first, cursor paging. Groups: production, qc, data, delivery, accounts.
- `GET /api/super/team-progress?days=` — Team progress summed across every Production dataset.

**UI.**
- A "Super admin" header button opens a page with People (summary + access/role/active controls + create account) and Activity tabs.
- The Team progress page gains an "All datasets" scope for super admins.
- The Profile account table becomes role-aware: access toggles for admins, admin role options only for super admins.

## 5. Implementation sequence
1. RBAC, visibility, network rule, migration, bootstrap.
2. Account-management guards and tests.
3. Super-admin APIs and tests.
4. UI: page, profile table changes, Team progress scope.
5. Full checks and a browser walkthrough on a throwaway database copy.

## 6. Tests
- `python -m compileall api/app api/worker.py`
- `cd api && pytest -q`
- `node --check` on app.js and every module
- New `api/tests/test_super_admin.py`:
  - unauthorized / user / admin / super admin on each `/api/super/*` endpoint
  - admin cannot create, edit or see super admins, and cannot create or edit admins
  - super admin can set an admin to office-only, and that admin is then blocked off-network
  - super admin is never blocked
  - the last super admin is protected
  - visibility of super-admin work in point history and Team progress
  - bootstrap promotion
  - migration default for existing admins

## 7. Rollout
- **Local:** set `SUPER_ADMIN_EMAILS` and walk through the page.
- **Preview/staging:** verify that an admin cannot see super-admin rows.
- **Production:** set `SUPER_ADMIN_EMAILS` in Railway before deploying.

## 8. Rollback
Redeploy the previous release. `SUPER_ADMIN` accounts are then an unknown role with no permissions, so they lose access. Before rolling back, set their role back to `ADMIN` (SQL `UPDATE users SET role='ADMIN' WHERE role='SUPER_ADMIN'`). The migration only sets `remote_access` for admins and needs no rollback.

## 9. Decision log
- 2026-10-08: First super admin comes from server configuration (`SUPER_ADMIN_EMAILS`), not from the app (user decision).
- 2026-10-08: Only super admins create or edit admin accounts (user decision).
- 2026-10-08: Existing admins keep "anywhere" until changed, so the upgrade locks no one out (user decision).
- 2026-10-08: "Everyone's work" = activity feed + per-person summary + Team progress across all datasets (user decision).
- 2026-10-08: Reuse the Team progress page with an "All datasets" scope rather than a second copy of the charts.

## 10. Progress
- [x] 2026-10-08 RBAC, visibility, network, migration `20261008_0013`, `SUPER_ADMIN_EMAILS` bootstrap
- [x] 2026-10-08 Account guards (admins manage users only; self-demotion and last-super-admin protection)
- [x] 2026-10-08 Super-admin APIs. The all-datasets Team progress was first O(datasets × accounts); it now preloads accounts and audit rows and skips idle per-dataset rows (49 s → 3 s on a test database with 958 active datasets).
- [x] 2026-10-08 UI: Super admin page (People, Activity), Team progress "All datasets" scope, role-aware Profile account table
- [x] 2026-10-08 pytest 208 passed (`tests/test_super_admin.py` + updated account tests); browser walkthrough 18/18 on a throwaway DB copy (deleted)
