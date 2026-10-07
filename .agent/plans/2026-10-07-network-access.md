# Office-network restriction for users, with per-user remote access

## 1. Outcome
- Admins can sign in and work from anywhere.
- When an admin turns the restriction on, USER accounts can only sign in and call the API from listed office networks. Someone who leaves the network mid-session is stopped on their next request, with a clear message.
- An admin can give individual users access from anywhere.
- The admin's Profile page shows the address the server sees for them, so the office's public IP can be added from the office with one click.

## 2. Current behavior
Any active account with valid credentials can use the app from anywhere. There is no network policy.

## 3. Constraints / invariants
- Railway sees the office's public (NAT) address, never LAN addresses such as 192.168.3.100. When running behind Railway, private ranges are rejected with an explanation.
- The client address comes from Railway's edge header `X-Real-IP`, not the client-controllable left-most `X-Forwarded-For`. `CLIENT_IP_HEADER` overrides the header name. Locally the direct socket address is used. If a configured header is missing, the request is treated as off-network.
- The restriction is off by default (no lock-out on deploy), cannot be enabled with no networks listed, and never applies to admins.
- Every policy change, remote-access change and blocked sign-in is audited.
- Additive migration only. Tests cover unauthenticated, wrong-role and happy paths.

## 4. Design
- Migration `20261007_0011`:
  - `users.remote_access` (bool, default false)
  - `app_settings` (key, value_json, updated_by, updated_at)
- `app/network_access.py` (no auth imports): `client_ip(request)`, `get_network_policy`, `set_network_policy`, `user_network_allowed(db, user, ip)`.
- `auth.current_user` returns 403 `network_not_allowed` for blocked users.
- `login` returns 403 with an explanation and audits `LOGIN_BLOCKED_NETWORK`.
- `GET/PUT /api/admin/network-access` (user.manage): returns the policy, the caller's IP and whether that IP is on a listed network.
- `PUT /api/users/{id}` accepts `remote_access`.
- UI:
  - admin Profile gets a **Network access** card: toggle, network list with labels, "Add my current network", and the current IP
  - the users table gets an "Access from" column (Office only / Anywhere)
  - the frontend signs out with an explanation on `network_not_allowed`

## 5. Implementation sequence
Migration/model → network_access module → auth/login enforcement → admin API → tests → UI → browser check.

## 6. Tests
`tests/test_network_access.py`:
- policy endpoint auth (401/403/200)
- validation: bad CIDR, empty enable, private range behind Railway
- enforcement on login and on existing tokens
- admin exemption and remote_access exemption
- header handling: `X-Real-IP` used only when configured; a missing configured header is denied

## 7. Rollout
Deploy (restriction off). An admin opens Profile → Network access from the office, clicks "Add my current network", checks that "You're connecting from" matches, then turns the restriction on. Users who work remotely are switched to "Anywhere".

## 8. Rollback
Turn the restriction off in the UI. That takes effect immediately with no deploy. Or redeploy the previous release; the new columns and table are ignored.

## 9. Decision log
- Kept in the database, not environment variables, so admins change it in the app without a redeploy.
- `X-Real-IP` comes from Railway's edge; the left-most `X-Forwarded-For` is spoofable and is not used.

## 10. Progress
- [x] 2026-10-07 implemented: migration 0011, `network_access.py`, enforcement in `current_user` and login, admin API, Profile → Network access card, users table "Access from" toggle, sign-out message on `network_not_allowed`.
- [x] 2026-10-07 pytest 154 passed (4 new). Browser on a throwaway copy: 15/15 (enable guard, add current network, user allowed/blocked, open session cut off, admin exempt, Anywhere toggle, off restores).
