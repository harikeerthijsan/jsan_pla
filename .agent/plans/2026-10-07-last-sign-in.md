# Last sign-in time and area for admins

## 1. Outcome
Admins see each account's last sign-in time (with the address in a tooltip) and, when the person shared it, the browser location. Clicking the location opens Google Street View there. Everyone sees their own last sign-in on their Profile page.

## 2. Current behavior
Sign-ins were recorded only for rate limiting. The `Permissions-Policy` header blocked geolocation on every page.

## 3. Constraints / invariants
- Location comes from the browser and only with the person's permission (product decision; no third-party IP-location service). Refusal is recorded as "denied".
- Only the latest sign-in is kept per account, with no history of places. Only admins (`user.manage`) see other people's records.
- A location is accepted only within 15 minutes of a sign-in, and is never requested on a page reload.
- Additive migration only.

## 4. Design
- Migration `20261007_0012` adds to `users`: `last_login_at`, `last_login_ip`, `last_login_location_status` (pending/shared/denied/unavailable), `last_login_latitude`, `last_login_longitude`, `last_login_accuracy`, `last_login_location_at`.
- Login records the time and IP, resets the location to pending, and clears the old coordinates.
- `POST /api/auth/sign-in-location` (signed-in user, also allowed during a forced password change) validates the coordinates.
- `Permissions-Policy` is now `geolocation=(self)` (camera and microphone stay blocked).
- UI:
  - `captureSignInLocation()` runs after a real sign-in
  - the users table gets a **Last sign-in** column with a 📍 area button
  - the Profile page shows a "Last sign-in" fact

## 6. Tests
`tests/test_sign_in_tracking.py`:
- recording and replacement on a new sign-in
- admin-only listing
- validation and the 15-minute window
- forced-password-change path
- header policy

Browser on a throwaway copy, 7/7:
- location shared vs refused
- no prompt on reload
- the Street View link

## 8. Rollback
Redeploy the previous release; the columns are ignored.

## 10. Progress
- [x] 2026-10-07 implemented. pytest 159 passed. The browser check found and fixed the `geolocation=()` header that would have blocked every location prompt.
