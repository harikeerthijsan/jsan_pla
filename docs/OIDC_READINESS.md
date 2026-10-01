# OIDC / SSO readiness gate

Production identity federation must not be implemented from guessed tenant values or claim mappings. Before replacing the named-local-account interim mode, JSAN must provide and approve:

1. Identity provider and tenant/issuer URL.
2. Registered browser/API client IDs and the API audience/resource identifier.
3. Authorization, token, logout, discovery and JWKS endpoints.
4. Redirect URIs for local, preview, staging and production.
5. Required scopes and the stable subject, email and display-name claims.
6. Group/role claims and an approved mapping to `ADMIN`, `PROGRAM_MANAGER`, `DELIVERY_MANAGER`, `DELIVERY_USER`, `QC_LEAD`, `QC_REVIEWER` and `CUSTOMER_VIEWER`.
7. Whether users are pre-provisioned, just-in-time provisioned, or SCIM-managed.
8. MFA/conditional-access policy owned by the identity provider.
9. Token/session lifetime, logout and emergency local-admin recovery policy.
10. A staging test account for every supported role.

## Required implementation acceptance

- Use Authorization Code with PKCE for the browser and backend verification of issuer, audience, signature, expiry and nonce/state.
- Do not trust an unverified browser-supplied role. Resolve permissions from an approved IdP mapping and/or server-side user record.
- Disable password login in production after OIDC staging acceptance; retain an audited break-glass procedure only if JSAN security approves it.
- Add unauthenticated, invalid-token, wrong-role, expired-token and happy-path tests.
- Audit successful/failed login, logout, provisioning and role changes without logging tokens or secrets.
- Validate the complete flow in isolated staging before promotion.

Until these inputs are supplied and accepted, the application continues to use named local accounts with API-enforced RBAC. This is an explicit external dependency, not a completed OIDC implementation.
