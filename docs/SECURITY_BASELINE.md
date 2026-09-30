# Security baseline

Target: OWASP ASVS Level 2 practices for a business application handling customer operational/geospatial data.

## Required before external/customer production
- Named user accounts; no shared admin login.
- Rotate any credential ever pasted into chat/tickets/email.
- Replace local password-only admin auth with enterprise OIDC/SSO where available; enforce MFA at the identity provider.
- Role-based authorization on every write/admin/reviewer endpoint, not only in the UI.
- Short-lived access tokens/sessions and backend verification on every request.
- Explicit CORS allowlist.
- Private object storage with short-lived presigned URLs.
- Upload authorization, file-size limits, extension/content validation, safe object-key generation, and malware/content scanning where required by customer policy.
- TLS only; secure headers; no secrets in browser config.
- Structured audit log for login, upload, processing, reviewer decisions, correction requests, approvals, and admin changes.
- Rate limits on login, presign, upload-finalize, and expensive processing endpoints.
- Separate staging/production secrets, database, buckets, and identities.
- Dependency and container image scanning in CI.

## Data handling
Treat workbooks and LiDAR as confidential customer data unless the contract states otherwise. Store only what the workflow requires, define retention, and make deletion a controlled audited action.
