# Sign in with an email code

## 1. Outcome
The sign-in card has two tabs: **Password** (unchanged) and **Email code**. With Email code, a person types their email, receives a 6-digit code (sent through Brevo, or SMTP), enters it, and is signed in. Admins can set real email addresses for accounts, so that staff accounts created with placeholder addresses can use it.

## 2. Current behavior
- `POST /api/auth/login` (`api/app/main.py`) checks the password, rate-limits failures per IP and name, refuses deactivated accounts and off-network users, and records the last sign-in.
- Email addresses can't be changed in the app. Seeded staff accounts use `*@polegrid.jsan.local`, which can't receive mail.
- The app sends no email.

## 3. Constraints / invariants
- AGENTS #9: unauthorized, wrong-role and happy-path tests for every new or changed route.
- AGENTS #10: no weakening of startup guards. The development "console" mail mode (code printed to the server log) is refused in staging and production.
- No account enumeration: requesting a code always returns the same response.
- Codes: 6 digits from `secrets`, stored only as an HMAC (keyed with `JWT_SECRET`), valid 10 minutes, single use, invalid after 5 wrong attempts. A new request replaces the previous code.
- Rate limits:
  - per address: 60 s between requests, at most 5 per 15 minutes
  - per IP: at most 20 requests per 15 minutes
  - verification failures share the existing per-IP/name login lock
- Code sign-in enforces exactly the same account rules as passwords: deactivation, the office network and forced password change.
- Railway Hobby blocks outbound SMTP, so the default production transport is Brevo's HTTPS API. SMTP remains available locally and on Railway Pro.
- Additive migration only.

## 4. Design
**Migration `20261008_0014`.** New table `email_login_codes`: `user_id`, `code_hash`, `created_at`, `expires_at`, `attempts`, `used_at`, `request_ip`.

**`api/app/mailer.py`.** `send_email(to, name, subject, text, html)`. The transport comes from `EMAIL_PROVIDER`:
- `brevo`: `BREVO_API_KEY`
- `smtp`: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SECURITY`
- `console`: development only
- unset: email sign-in disabled

The sender comes from `MAIL_FROM_EMAIL` and `MAIL_FROM_NAME`.

**`api/app/email_login.py`** (router):
- `GET /api/auth/methods`
- `POST /api/auth/email-code/request`
- `POST /api/auth/email-code/verify`

Sign-in completion is shared with password login (`complete_sign_in`).

**Email editing.** `PUT /api/users/{id}` accepts `email`: valid, unique and lower-cased, with the same authority rules (admins edit users; super admins edit admins). Audited as `CHANGE_EMAIL`.

**UI.**
- Password / Email code tabs on the sign-in card. The Email code tab appears only when a mail provider is configured.
- Code entry with resend countdown and "use a different email".
- A "Change email" action in the Profile and Super admin account tables.

## 5. Implementation sequence
1. Migration, model, mailer.
2. Code request/verify routes and shared sign-in completion.
3. Email editing.
4. UI.
5. Tests, docs, full checks and a browser walkthrough with the console transport on a throwaway database copy.

## 6. Tests
`api/tests/test_email_login.py`:
- methods endpoint
- generic response for unknown, inactive and undeliverable addresses
- successful sign-in
- wrong code, attempt lock, expiry and reuse
- per-address cooldown
- network block and deactivation
- forced password change preserved
- Brevo request shape
- console mode refused in production
- email editing: unauthorized, user, admin on user/admin, super admin, duplicates

Plus the standard commands (`compileall`, `pytest -q`, `node --check`).

## 7. Rollout
- **Local:** `EMAIL_PROVIDER=console`.
- **Staging:** Brevo with a verified sender.
- **Production:** set `EMAIL_PROVIDER=brevo`, `BREVO_API_KEY`, `MAIL_FROM_EMAIL` and `MAIL_FROM_NAME` in Railway, then set real email addresses for the staff accounts.

## 8. Rollback
Redeploy the previous release. Password sign-in is unchanged. The `email_login_codes` table is ignored by older releases.

## 9. Decision log
- 2026-10-08: Brevo HTTPS API as the mail service (user decision). SMTP is also supported, because Railway Hobby blocks SMTP ports.
- 2026-10-08: Admins edit email addresses (super admins for admins) (user decision).
- 2026-10-08: Every active account with a deliverable address may use email codes (user decision).

## 10. Progress
- [x] 2026-10-08 Migrations `20261008_0014` (codes) and `20261008_0015` (sign-in email), mailer (Brevo/SMTP/console), request/verify routes, shared `complete_sign_in`
- [x] 2026-10-08 Sign-in email instead of editing the account email: the account email is the identity in tokens and work records (`created_by`, reviewer, presence), so changing it would sign people out and detach their history
- [x] 2026-10-08 UI: Password / Email code tabs (hidden when no provider), resend countdown, auto-submit; sign-in email shown and editable in Profile and Super admin tables
- [x] 2026-10-08 pytest passes (test_email_login.py: 15 incl. production guard); browser walkthrough 11/11 with console mail on a throwaway copy (deleted)
- Note: the dev server reloaded mid-edit and applied an early 0014; the sign-in email column was therefore moved to its own revision 0015 so every database upgrades correctly.
