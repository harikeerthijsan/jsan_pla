# Employee directory for super admins

## 1. Outcome
Super admins have a **Directory** tab on the Super admin page. It lists every JSAN employee imported from the HR export (CSV), with search, filters and sorting.

From there a super admin can:
- give any employee access to the app as **User, Admin or Super admin**, one at a time or in bulk;
- get a temporary password for them;
- activate or deactivate their access, reset their password, and change their role or where they may work from;
- edit and delete directory entries;
- import newer CSV exports.

Granting access creates the application account straight away (`users` row), linked to the directory entry, so the details flow into the app automatically.

## 2. Current behavior
- Accounts are created one by one: on the Super admin People tab, or by admins on their Profile page.
- `PUT /api/users/{id}` already handles role, active, remote access and password, with its safety rules:
  - only super admins manage admin roles;
  - at least one active admin and one active super admin must remain;
  - you can't deactivate yourself;
  - deactivating or resetting a password signs that account out.
- HR data is not stored anywhere in the app.

## 3. Constraints / invariants
- AGENTS #4: the employee CSV is customer/personal data. It is never committed; it is loaded locally with the CLI, and on deployed environments through the page's Import button.
- AGENTS #6: work records reference account emails. App accounts are therefore never hard-deleted from the directory. "Remove access" deactivates the account. Deleting a directory entry is refused while its account is still active.
- AGENTS #9: every new route has unauthorized, wrong-role (admin, user) and happy-path tests.
- All routes need `super.view`, which only SUPER_ADMIN has. Role changes on linked accounts go through the existing `PUT /api/users/{id}`, so its guards still apply.
- Temporary passwords:
  - generated server-side with `secrets`;
  - returned once and never stored in plain text;
  - `must_change_password` is set, and `token_version` is bumped on reset.
- Treat the CSV as untrusted:
  - size cap 2 MB and 5,000 rows;
  - required columns Name and Email;
  - emails are validated, and bad rows are skipped and reported;
  - values are rendered only as escaped text.
- Additive migration only.

## 4. Design
**Migration `20261009_0016`.** New table `employee_directory`:
- `name`, `jsan_id` (unique), `employee_id`, `email` (unique, lower-case)
- `department`, `designation`, `date_of_joining`, `experience_years`
- reference fields from the HR system: `source_role`, `source_password_set`, `source_last_sign_in`, `submission_status`
- `user_id` → `users.id` (unique, nullable)
- `source`, `created_at`, `updated_at`, `updated_by`

**`api/app/employee_directory.py`** (router `/api/super/directory`):
- `GET ''`: entries with their linked account (or a matching account found by email), plus facets.
- `POST /import`: JSON body `{filename, csv}`. Upsert by email, then JSAN ID. Returns counts and skipped rows. Audit `IMPORT_EMPLOYEE_DIRECTORY`.
- `POST ''`, `PUT /{id}`, `DELETE /{id}`:
  - add, edit and delete entries;
  - an edit syncs the name to the linked account;
  - the email is locked once an account is linked.
- `POST /{id}/grant` and `POST /grant` (bulk, ≤ 200):
  - create the account, with the JSAN ID as username, the role chosen (USER/ADMIN/SUPER_ADMIN), a temporary password and the "works from" setting;
  - or link the existing account with that email.
- `POST /{id}/reset-password`: new temporary password for the linked account.
- CLI: `python -m app.employee_directory import <csv>` for local loading.

**Frontend** (`web/assets/modules/employee-directory.js`, Directory tab):
- KPI strip;
- search and filters (access status, app role, department, designation, HR role), with sortable columns;
- row selection with bulk grant and deactivate;
- per-row actions;
- dialogs for grant, credentials (copy, CSV download), add/edit and import.

## 5. Validation
- pytest:
  - auth matrix;
  - import parsing (BOM, `undefined`, DD-MM-YYYY dates, bad emails);
  - upsert;
  - grant creates a linked account that can sign in;
  - an existing account is linked rather than duplicated;
  - reset password;
  - edit syncs the name;
  - delete is refused while access is active;
  - migration head.
- A browser walkthrough on a throwaway database copy.

## 6. Progress
- [x] Migration, model, router and CLI
- [x] Tests (7 API + 1 frontend; full suite 239 passed)
- [x] Frontend tab
- [x] Local import of the HR CSV (172 added) and browser walkthrough (25/25 on a throwaway copy)
