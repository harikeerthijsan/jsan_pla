# End sessions on password change, deactivate accounts, block lost point edits

## 1. Outcome
- Changing or resetting a password, or deactivating an account, ends every existing sign-in for that account. The person who changed their own password stays signed in on the device they used.
- Admins can deactivate and reactivate accounts. A deactivated account cannot sign in or use any API; its work and audit history stay.
- Saving or deleting a production point that someone else changed since it was loaded is refused (409) with who changed it, instead of silently overwriting.

## 2. Current behavior
- `api/app/auth.py::create_token` issues an 8-hour HS256 token (`sub`=email) that stays valid after any password change.
- `api/app/main.py` `/api/users` supports list/create/update only; no disable.
- `PUT/DELETE /api/projects/{id}/production-annotations/{aid}` apply unconditionally (last write wins). The workbook editor already has a snapshot check.

## 3. Constraints / invariants
- Additive migration only; existing rows get `token_version=0`, `is_active=true`, `revision=1`.
- Auth changes carry unauthorized, wrong-role and happy-path tests.
- Seeding never reactivates a deactivated account.
- An admin cannot deactivate themselves or the last active admin.

## 4. Design
- Migration `20261007_0008`: `users.token_version` (int, default 0), `users.is_active` (bool, default true), `production_annotations.revision` (int, default 1).
- Token payload adds `ver`. `current_user` rejects (401 `session_ended`) a token whose `ver` differs from `users.token_version`, and rejects inactive users (401).
- `token_version` increments on own password change (response returns a fresh token), admin password reset, and deactivation.
- Login: correct password on a deactivated account → 403 "This account is deactivated".
- `PUT /api/users/{id}` accepts `active`. Self or last active admin → 409. Audit `DEACTIVATE_USER` / `REACTIVATE_USER`.
- Annotation `revision` increments on every update. `PUT` body and `DELETE` query accept `expected_revision`; on mismatch → 409 naming `modified_by`. The frontend always sends it and reloads points on conflict.
- Profile page Users table: Active/Deactivated status plus Deactivate/Reactivate buttons.

## 5. Implementation sequence
Migration + models → auth/session checks → users endpoint → annotation revision → frontend → tests.

## 6. Tests
`pytest -q`, including `tests/test_sessions_accounts_conflicts.py`. `node --check web/assets/app.js`. Browser: reset ends another browser's session; deactivate blocks sign-in; conflicting point save shows the message.

## 7. Rollout
Staging, then production. The migration is additive and no variables change.

## 8. Rollback
Redeploy the previous release. The new columns are ignored by older code. Tokens issued by the new release carry an extra `ver` claim the old code ignores.

## 9. Decision log
- Token version counter instead of a server-side session table: one integer per user, no extra lookups beyond the user row already loaded.
- Integer revision instead of comparing `updated_at`, which avoids timestamp precision differences between SQLite and PostgreSQL.

## 10. Progress
- [x] 2026-10-07 implemented: migration 0008, session versions, deactivation with self/last-admin guards, atomic point revisions, Profile Users table controls, sign-out reason on the login page.
- [x] 2026-10-07 pytest 131 passed. Browser: password change signs out the other device with a reason; deactivate/reactivate from the Users table; stale point delete refused with the editor's name and the list reloaded.
