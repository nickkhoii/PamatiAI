# Security

The prototype is a foundation and must not accept real student data yet. Threats include cross-student access, compromised reviewer accounts, insider content access, consent bypass, leaked media, prompt injection and model supply-chain compromise.

Implemented controls: deny-by-default pure RBAC/resource policy, explicit development origins, restricted trusted hosts, sanitized readiness errors, non-root containers, internal MySQL network, environment configuration and ignored secret files. No authentication or data endpoints are exposed. Public health endpoints reveal only service state. Browser status requests use a server-side fixed API origin and never expose database credentials.

Before authenticated features: Argon2id hashing; generic login errors; login throttling; staff MFA; opaque random session identifiers or signed JWTs with issuer, audience, expiry and rotation checks. Prefer HttpOnly Secure SameSite cookies with explicit CSRF checks for mutations. Revoke sessions on logout, password changes and role changes. Do not store tokens in localStorage. Never trust client role claims. Require ownership and assignment checks on every resource, including exports and media URLs. Administrators do not inherit reviewer privileges.

Use TLS in production, distinct migration and runtime database credentials, least-privilege SQL grants, secret management, encrypted storage and backups, bounded request/media sizes and dependency scanning. Sanitize all logs; exclude messages, media, passwords, tokens and connection strings. Audit access and decisions without duplicating sensitive payloads. Retention and deletion policies must cover replicas, derived observations and backup expiry. Validate restoration and deletion workflows before participant onboarding.

Production must use explicit hosts/origins, secure secret values and debug disabled. Compose credentials are supplied locally and are development-only. The foundation has no JWT signing secret because token issuance is not yet implemented.
