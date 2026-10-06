# Staff accounts, profile page and admin-only uploads

## 1. Outcome
- Two admins (`Admin001`, `Admin002`) and twenty users (`JSAN001`–`JSAN020`) exist in every environment, including production after deploy, all starting with one shared initial password.
- Everyone signs in with a username (email still works) and must change the shared password on first sign-in.
- A Profile page lets each person change their display name and password; admins also reset other users' passwords there.
- Only admins upload (LiDAR, Excel, GeoJSON, QC Excel) or create datasets.
- Production work (saved LiDAR points and the pole location/elevation they verify): admins see everyone's; users see and edit every non-admin user's work but never an admin's.
- `internal_id` cells in Workbook Data are read-only for users (like Pole Number) and editable by admins.
- The Production pole search finds poles by Pole Number or internal_id.

## 2. Current behavior
- `api/app/seed.py::seed_admin` creates one admin from `ADMIN_EMAIL`/`ADMIN_PASSWORD` when the users table is empty.
- `users` has email/name/role/password_hash; login is by email (`api/app/main.py::login`).
- `api/app/rbac.py` gives `upload.create`/`project.create` to several non-admin roles.
- Annotations (`production_annotations.created_by`) are listed for everyone.
- `api/app/workbook_editor.py` locks only the Pole Number column.

## 3. Constraints / invariants
- No credential in git: the shared password comes from the `STAFF_INITIAL_PASSWORD` secret. Seeding never overwrites an existing account's password.
- Production startup guard is extended, never weakened: a configured `STAFF_INITIAL_PASSWORD` must be ≥12 chars and not a known default.
- Schema change is additive (migration 0007); existing SQLite/Postgres rows are kept.
- Auth changes are tested for unauthorized, wrong-role and happy paths.

## 4. Design
- Migration `20261006_0007`: `users.username` (unique, nullable) and `users.must_change_password` (bool, default false).
- New role `USER`: Production/QC/Delivery workspaces, annotate, edit workbook, review findings, create/resolve corrections. No upload, dataset creation, processing, revisions, approval or user management.
- `upload.create` and `project.create` become ADMIN-only for all roles. New ADMIN-only permissions are `work.view_all` and `workbook.edit_internal_id`.
- `seed_staff_accounts` runs on every API start: it adds missing accounts with `must_change_password=True` and an audit row.
- Login accepts a username or an email. `current_user` returns 403 `password_change_required` for every route except `/api/auth/me`, `/api/auth/change-password` and `/api/auth/profile` while the flag is set.
- Endpoints: `POST /api/auth/change-password`, `PUT /api/auth/profile`. Admin reset uses `PUT /api/users/{id}` and sets `must_change_password`.
- Admin work hiding is by creator role at query time. Hidden rows return 404 on update/delete, and verified pole fields set by an admin are blanked for users.

## 5. Implementation sequence
1. Migration + model + seed + guard.
2. RBAC + auth endpoints + forced password change.
3. Visibility filter + internal_id lock.
4. Frontend: username login, Profile page, admin user list, upload gating, search placeholder, internal_id read-only.

## 6. Tests
`python -m compileall api/app api/worker.py`, `cd api && pytest -q`, `node --check web/assets/app.js`.
Scenarios: seeding idempotent; username login; forced change blocks other APIs; wrong current password rejected; USER cannot upload/create (403); USER cannot see/edit admin annotations; USER sees/edits other user's; USER cannot edit internal_id; admin can.

## 7. Rollout
Set `STAFF_INITIAL_PASSWORD` in Railway staging, deploy, sign in as JSAN001, change password; then production.

## 8. Rollback
Redeploy the previous release. Migration 0007 is additive, so its columns are ignored by older code. Seeded accounts can be removed by an admin if unwanted.

## 9. Decision log
- Shared password from a secret, not code (AGENTS invariant 4). Forced first-login change, because one password shared by 22 accounts is otherwise a standing risk.
- Workbook Excel stays one shared file; its values cannot be hidden per author, so "work" visibility applies to saved points and pole verification.

## 10. Progress
- [x] 2026-10-06 migration 0007, `seed_staff_accounts`, production guard, `USER` role, admin-only uploads.
- [x] 2026-10-06 username login, forced first-sign-in change, `/api/auth/change-password`, `/api/auth/profile`, temporary admin resets.
- [x] 2026-10-06 admin work hidden from users (annotations, GeoJSON export, verified pole fields); internal_id lock.
- [x] 2026-10-06 Profile page, upload gating, internal_id search. pytest 124 passed; browser check 21/21.
- [x] 2026-10-06 local DB seeded (backup `api/pla_qc-before-staff-accounts.db`, git-ignored).
- [ ] Set `STAFF_INITIAL_PASSWORD` in Railway staging, then production.
