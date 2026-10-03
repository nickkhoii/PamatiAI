# Authentication deployment and API

## Institutional onboarding

Registration is invite-only by default. An administrator creates an email-bound, expiring invitation with STUDENT, COUNSELOR or ADMIN. The recipient opens `/auth/invite`, submits matching institutional email, display name and a password; the server consumes the invitation and provisions the appropriate profile. Possession of the email-delivered invitation verifies the recipient's mailbox. Invitations are single-use; issuing a newer invitation invalidates the older one.

Optional public registration is controlled by PUBLIC_REGISTRATION_ENABLED and INSTITUTIONAL_DOMAINS (a JSON list of allowed domains). It always creates an inactive STUDENT; a single-use email activation link verifies and activates the account. Administrator activation cannot bypass email verification. Deactivation invalidates outstanding user challenges as well as sessions. Profile editing currently supports display name; institutional email changes require a separate verification workflow and cannot be made via profile payloads.

Run from `pamati-ai/backend` after configuring DATABASE_URL:

```powershell
../.venv/Scripts/python.exe -m alembic upgrade head
../.venv/Scripts/python.exe -m app.database_commands seed
# First administrator only: variables are local to this process and have no defaults.
$env:BOOTSTRAP_ADMIN_EMAIL = Read-Host 'Institutional administrator email'
$env:BOOTSTRAP_ADMIN_NAME = Read-Host 'Display name'
$env:BOOTSTRAP_ADMIN_PASSWORD = [System.Net.NetworkCredential]::new('', (Read-Host 'Password (15+ characters)' -AsSecureString)).Password
try { ../.venv/Scripts/python.exe -m app.bootstrap_admin }
finally { Remove-Item Env:BOOTSTRAP_ADMIN_EMAIL, Env:BOOTSTRAP_ADMIN_NAME, Env:BOOTSTRAP_ADMIN_PASSWORD }
```

Bootstrap refuses existing accounts or a database with an administrator. Run it once under the institution's provisioning procedure. Thereafter use administrator invitations; do not seed development accounts in production.

## Email delivery

Configure AUTH_DELIVERY_KEY with a Fernet key generated using the command in `.env.example`. Store it in a secret manager; the API and dispatcher must share the key. Configure AUTH_PUBLIC_URL (exact frontend origin, HTTPS in production, no trailing slash), SMTP_HOST, SMTP_PORT, SMTP_FROM and, if required, SMTP_USERNAME/SMTP_PASSWORD. Registration, invitations and recovery fail closed with 503 when delivery is unconfigured. Existing login remains usable.

The API atomically queues an encrypted link payload with its challenge. Only the challenge's token hash is stored unencrypted. Run `python -m app.auth_mail` periodically as a scheduled job, or `docker compose run --rm backend python -m app.auth_mail`. The dispatcher uses validated SMTP STARTTLS, locks deliveries, skips consumed/expired challenges, deletes payloads after delivery and caps failures at five attempts. Monitor unsent/exhausted rows; retry or reissue links under an operational procedure. SMTP delivery is at-least-once; a crash after sending can send the same single-use link again. Keep expired challenge/session records through their replay-detection lifetime, then clean up according to retention policy. Do not log mail contents or the delivery key.

## API contract

All routes below use `/api/v1`. Login/refresh return `{access_token, refresh_token, token_type, expires_in}` for non-browser API clients. Send `Authorization: Bearer <access_token>` on protected routes. Refresh takes `{token: <refresh_token>}`; reset takes `{token, password}`. Browser forms at `/auth/login`, `/auth/register`, `/auth/profile` and the email-link routes use the cookie gateway and never expose these tokens to JavaScript. Session renewal is explicit through the profile page; backend expiry and absolute session lifetime remain authoritative. Serialize refresh requests per browser session; simultaneous use of one refresh token triggers replay revocation.

| Route | Purpose/access |
| --- | --- |
| POST /auth/register | Invitation onboarding or verified public STUDENT registration |
| POST /auth/login | Generic errors; throttled credential verification |
| POST /auth/refresh | Rotate refresh and access token; replay revocation |
| POST /auth/logout, /auth/logout-all | Authenticated session-family/all-session revocation |
| POST /auth/logout-session | Revoke using a refresh secret, including after access expiry |
| POST /auth/forgot-password | Generic response; encrypted delivery queue |
| POST /auth/reset-password | Expiring single-use challenge; revoke all sessions |
| POST /auth/activate | Expiring single-use email activation |
| POST /auth/change-password | Current password required; revoke all sessions |
| GET/PATCH /me | Authenticated profile; no role/email escalation |
| POST /admin/invitations | ADMIN + accounts:manage |
| GET /admin/users | ADMIN + accounts:manage; bounded user listing |
| PATCH /admin/users/{id}/activation, /role | ADMIN + accounts:manage; session revocation |
| PUT /admin/assignments | ADMIN + accounts:manage; grant/revoke counselor assignment |
| GET/PUT /admin/settings[/key] | ADMIN + configuration:manage; validated existing non-secret setting |
| GET/POST /students/{id}/conversations | Owner; assigned/consenting counselor can list |
| GET/DELETE /conversations/{id} | Derived owner checks; deletion is owner-only logical hiding |
| GET/PUT/DELETE /students/{id}/consent | Owner only; versioned consent and withdrawal |
| GET /students/{id}/trends | Owner or authorized counselor; active longitudinal consent required |
| POST/GET /students/{id}/support-requests | Owner requests; authorized counselor can read |
| POST/GET /students/{id}/data-controls | Owner requests/lists export or erasure requests |
| GET /students/{id}/safety-signals, /reviews, /referrals | Assigned, consenting counselor only |
| POST /safety-signals/{id}/reviews | Assigned, consenting counselor; record-derived ownership |
| POST /students/{id}/referrals; PATCH /referrals/{id} | Assigned, consenting counselor; review/referral ownership checks |

`authenticated_user`, `require_role`, `require_permission` and `authorize_student` are reusable dependencies/policy checks. Any new sensitive route must use them before reading content or performing writes. Unknown permissions and unknown institutional roles deny by default. Administrators do not inherit history/review permissions; frontend navigation is never an authorization boundary.

Deployment must keep the backend private behind the gateway or a trusted edge, use explicit origins/hosts and HTTPS, and apply request/connection limits at the edge. Backend IP throttling deliberately ignores caller-supplied forwarding headers; when using the browser gateway, its IP bucket is shared, so size or partition ingress capacity and add trusted edge throttling for deployment traffic. Configure runtime SQL privileges for the new session/challenge/delivery/rate-limit/request tables, append-only audit INSERT/SELECT, and permitted user/profile/membership/assignment/configuration writes. Seeding and migrations use a separate provisioning credential. No changes to the real `.env` are made by this implementation.

## Validation

`test_auth.py` exercises real HTTP dependencies and persisted sessions against SQLite, and against an explicitly configured MySQL `_test` database. It proves cross-user read/write denial, assigned versus unassigned counselor access, current consent/permission enforcement, ADMIN content denial, single-use challenge expiry, role/deactivation revocation, refresh rotation/replay, and password recovery/change. The existing MySQL tests additionally enforce ownership, consent, evidence and append-only audit constraints. All fixtures roll back their data.

Consent PUT requests now require the current onboarding policy version and `acknowledged: true`, plus the displayed `retention_version`; send `expected_version` to reject stale edits. Read `/api/v1/me/onboarding` for the disclosure/retention policy. Consent permission fields remain separate and default false. The authenticated browser gateway derives student IDs from `/me` and provides owner-scoped consent, records, support and privacy-request actions.
