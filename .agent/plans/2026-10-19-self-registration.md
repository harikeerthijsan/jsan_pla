# Self-registration for employees (User role only)

## 1. Outcome
A **Register** option on the sign-in page:
1. The person enters their work email and clicks **Submit**.
2. If the email is in the employee directory and has no account yet, they see their name and JSAN ID from the directory and choose a username and password.
3. That creates an active **User**-role account linked to their directory entry. The super admin directory immediately shows them with access, and they can then sign in.

Admin and Super admin accounts are still created only by a super admin.

## 2. Current behavior
- Accounts are created only by an admin (`POST /api/users`) or by a super admin granting access from the employee directory (`employee_directory.grant_access`). That issues a temporary password that must be changed.
- The directory row's `user_id` links it to the account. `employee_dict` reports `access` as none / pending / active / inactive.

## 3. Constraints / invariants
- **Decision by the user (2026-10-19):** no proof of email ownership. Being in the directory is enough. Email-code verification and super-admin approval were offered and declined.
- **Safeguards that keep that decision:**
  - Registration never touches an existing account. If the directory row is linked, or any user already has that email, the answer is "already has an account — sign in". So it can't be used to take over an account or reset a password.
  - The role is always `USER`. No request field can change it.
  - Attempts are throttled per IP and per email (`app.throttle`, shared across processes and replicas) to slow directory enumeration.
  - Passwords follow the existing rules: 12–256 characters, and not the same as the username or email.
  - Each registration is audited as `SELF_REGISTER` (email, username, directory id, IP).
- **Network rule unchanged:** office-network rules apply as for any user account. `remote_access` is false for User accounts, like a super-admin grant.
- **AGENTS #9 (auth change):** tests cover rejection cases (not in the directory, already registered, weak password, taken username, throttled) and the happy path, including signing in after registering. Neither endpoint needs to be signed in to use, by design.

## 4. Design
- **`app/registration.py`** (router):
  - `POST /api/auth/register/check {email}` returns `{name, jsan_id, suggested_username}`, or 404 (not in the directory), 409 (already has an account), 429 (throttled).
  - `POST /api/auth/register {email, username, password}` re-checks everything, creates the `USER` account (no forced password change), links the directory row, audits, and returns `{username, name}`.
- **UI:**
  - A "New here? Register" link under the sign-in form opens a register pane in the same card.
  - Step 1: email and Submit.
  - Step 2: shows the name and JSAN ID from the directory, then username (pre-filled), password and confirm.
  - On success it returns to sign-in with the username filled in.

## 5. Tests
`cd api && pytest -q`, plus a new `tests/test_self_registration.py`.

## 6. Rollout / rollback
- No schema change.
- Rollback: redeploy the previous release. Accounts already created stay as normal User accounts.

## 7. Progress
- [x] 2026-10-19 API + tests (tests/test_self_registration.py; full suite 327 passed, only the unrelated outputs/ hygiene check fails)
- [x] 2026-10-19 Sign-in page UI + browser check on a DB copy: unknown email message, directory name/JSAN ID shown,
  password mismatch caught, account created (User, active, linked; directory shows "active"), sign-in works
