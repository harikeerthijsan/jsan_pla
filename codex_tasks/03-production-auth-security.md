# Task: production authentication and authorization

Replace shared production credentials with named-user enterprise auth. Prefer standards-based OIDC and delegate MFA to the identity provider. Preserve a local development login only when APP_ENV is not production.

Acceptance criteria:
- Production startup refuses local shared-admin auth.
- Role checks exist on API endpoints.
- Session/token handling follows backend verification and expiry.
- Login/admin/upload endpoints have abuse controls.
- Secrets remain server-side.
- Security tests cover unauthenticated and wrong-role requests.
