# Security audit

Audit date: 2026-10-09. Scope: the repository's FastAPI API, Next.js gateway and UI, SQLAlchemy persistence, MySQL constraints/triggers, media handling, consent, research export and AI processing boundaries. This is a source review and local automated verification, not a certification or penetration test of a deployed institution.

All exercised accounts, messages, uploads and model outputs were synthetic. Live-MySQL tests use only the isolated `pamati_auth_test` schema on loopback port 3307. Participant schemas and real deployment secrets were not modified. Production service logs, institutional infrastructure, devices and external model endpoints were not available for inspection.

## Findings fixed

| Finding | Change and regression evidence |
| --- | --- |
| Validation errors could echo passwords, reset tokens and rejected conversation text | Replace FastAPI's input-bearing validation response with a generic 422. `test_security_audit.py` checks response, application logs and audit rows using private sentinels. |
| Unhandled exceptions could expose SQL parameters or provider content through tracebacks | Return a generic 500; log only an internally generated request ID and exception class. Enable SQLAlchemy parameter hiding in API, provisioning and migration engines. A deliberately sensitive database exception is absent from responses and captured logs. |
| JSON requests and chunked gateway requests could be buffered before size rejection | Apply an ASGI receive limit before parsing: 32 KiB for ordinary requests, configured media limits capped at 3 MB. Both gateway mutation handlers read bounded streams and cancel on overflow. Test declared and chunked limits, including the running production gateway. |
| API reads and inexpensive mutations lacked a common abuse budget | Add shared database-backed IP counters, 600 requests per 15 minutes, in addition to existing login/account and expensive-operation limits. Invalid bearer tokens and mutations are covered; rejection is 429 with Retry-After. Health/readiness probes are excluded. |
| Expired records remained usable until an erasure process ran | Apply retention deadlines, saved policy snapshots and current finite holds to conversation reads/turns, dashboard conversations/check-ins, analysis source availability, trend inputs, safety evidence and research export. Metadata-only privacy inventories remain available to their owner; hidden/expired check-ins do not expose their feeling. Expiry prevents ordinary use, without falsely claiming physical erasure. |
| Cached retention configuration could preserve an older, longer period | Refresh policy and hold rows using current shared locking reads; a cached-policy regression verifies that a shortened period takes effect. Text-analysis history also applies its own shorter analysis deadline while the conversation remains live. |
| Restoring a former counselor role could restore old assignments | Revoke assignments when the counselor role is removed. Restoring that role requires an explicit new assignment. Role changes also revoke sessions. |
| Cached consent/account state could authorize a reviewer after withdrawal | Use fresh locking reads of student state, latest consent and assignments at object authorization. The stale-identity-map regression verifies withdrawal wins. |
| Security-changing boolean fields accepted coerced values | Require explicit booleans for account activation and assignment revocation, as already required for consent. |
| Invalid media was recorded as a failed inference instead of rejected at the HTTP boundary | Validate WAV structure or all BMP-frame headers before job creation. Reject active SVG, archive payloads, malformed containers and unsupported content types; retain worker-side validation as well. |
| Browser defenses lacked a script CSP and transport policy | Apply per-request script nonces with strict-dynamic, no inline-script exemption in production, no framing/objects, restricted connections and form targets. Dynamic rendering supplies matching nonces to Next.js scripts. API responses have a restrictive CSP. Add HSTS in production, no-referrer, no-store, nosniff, frame denial and device permission restrictions. |
| Production accepted development boundary settings | Reject HTTP public authentication URLs, wildcard CORS/hosts and the known development database password in production settings. |
| Default access logs could contain search text or record IDs | Disable Uvicorn access logs in the image command, development Compose command and documented launch command. See the logging requirements below for external infrastructure. |
| Frontend lint was absent | Add TypeScript, React Hooks, accessibility and unsafe-HTML/eval checks, and include lint plus the production gateway tests in `scripts/check.ps1`. Remove the initially introduced vulnerable Next lint dependency chain. |
| Older tests rewrote immutable provenance under SQLite | Correct historical inference fixtures to insert their timestamps initially, and consent fixtures to append receipts. Retain MySQL immutability triggers. |
| Changed trend evidence could fail at a database trigger before controlled discard | Recheck sources before writing each dimension's lineage and flush validated edges together. The changed-source regression passes on SQLite and MySQL. |

## Control review

Authentication uses Argon2id password hashes, a 15–128 character new-password policy, dummy verification for unknown accounts, generic recovery responses and an encrypted email outbox. Opaque tokens are stored only as digests. Access expiration, absolute refresh-family expiration, rotation/replay rejection, logout, reset, deactivation and role-change revocation are enforced against database state. Browser tokens are HttpOnly, Secure in production and SameSite=Strict, and are not returned to browser JavaScript.

Authorization combines server-read roles, permissions and record ownership. Students cannot select another owner through a URL/body. Counselors require a live assignment, current reviewer-access consent and active accounts/profiles. Administrative account/configuration privileges do not grant conversation or review-content access. An unrecognized RESEARCHER role does not gain identifiable-data privileges. Research export is a restricted trusted-worker operation, not an administrator or researcher content endpoint.

The cookie gateway checks an exact configured Origin on mutations. Direct backend authentication uses bearer headers, not cookies, so the backend has no cookie-session CSRF boundary. CORS uses explicit origins with credentials disabled; TrustedHost restricts backend hosts. Keep `AUTH_PUBLIC_URL`, `CORS_ORIGINS` and `ALLOWED_HOSTS` aligned with the deployment.

Inputs have bounded schemas, allowlisted operations and field validation. SQLAlchemy binds data values; dashboard search escapes wildcard syntax. Provisioning's interpolated database name is restricted to an identifier pattern. Participant/provider text is rendered as React text, never trusted HTML. Lint prohibits unsafe HTML insertion and eval. CSP nonces are server-generated, overwrite incoming nonce headers and differ between requests.

Uploads use explicit raw bodies, narrow PCM WAV and uncompressed 24-bit BMP/frame-sequence formats, byte/duration/pixel/frame limits, server-generated private filenames and temporary cleanup. Archives, SVG and general video containers are not supported. Audio and visual permissions are separate, disabled by default, and checked before consuming media and again around processing/publication. There is no automatic microphone/camera capture; browser device access is denied by Permissions-Policy.

Consent receipts and processing provenance are immutable under MySQL. Supersession/withdrawal cancels pending/running work and blocks publication or research use. A completed inference does not become independent of source consent, source deletion or expiry. Raw-audio retention additionally requires the environment gate, database gate and student retention permission. Visual raw retention is not implemented. Holds extend authorized retention only; they confer neither access nor processing permission.

Audit rows record actor/action/resource/outcome/time, not messages, notes, passwords, tokens or connection strings. MySQL triggers reject audit updates/deletes. Application roles require a separate migration identity and least-privilege runtime grants; application RBAC is not database row-level security.

## Abuse-test coverage

| Requested scenario | Automated coverage |
| --- | --- |
| Student accesses another student's data | `test_auth.py`, `test_conversation.py`, `test_dashboards.py`, media and longitudinal API tests |
| Researcher accesses identifiable data without permission | `test_security_audit.py`; `test_research_export.py` identity exclusion, current/original research consent and suppression |
| Admin accesses conversations unnecessarily | Authentication, conversation, media, dashboard and longitudinal role-denial cases |
| Counselor accesses unassigned/withdrawn students | Authentication, dashboard, safety, media and stale-consent/role-restoration regressions |
| Audio/video processing without consent | Independent audio/visual denial cases verify no request-stream consumption, adapter execution or media files; video containers are unsupported |
| Processing after withdrawal or supersession | Consent, conversation, audio, visual, fusion, longitudinal and research-export tests, including changes during adapter execution |
| Deleted/expired records | Existing deletion/source-liveness tests; audit expiry regressions for reads, turns and dashboard counts; retained sources are required for derived use |
| Malicious/oversized uploads | HTTP SVG/archive/oversize tests; WAV/BMP structural, compression, pixel, timestamp, traversal and temporary-cleanup tests |
| Invalid tokens/expired sessions/API abuse | Authentication expiry/replay/revocation cases, persistent throttling, generic-budget regression and running gateway expiry/logout checks |
| Sensitive logging, CSRF, CORS, SQL injection and XSS defenses | Captured-log sentinels, database exception redaction, hostile Origin/CORS, injection-shaped search, CSP/nonce checks and unsafe-HTML lint |

## Verification

Local verification includes the complete SQLite/MySQL suite, including the final text-analysis expiry and cached-policy regressions. Reproduce the ordinary checks with `scripts/check.ps1`; enable real MySQL by setting `TEST_DATABASE_URL` to a dedicated schema ending in `_test` before running backend Pytest. Never use a participant schema for tests.

| Final check | Result |
| --- | --- |
| Backend Pytest, SQLite and MySQL 8.4.4 | **619 passed, 1 intentional SQLite skip**; no failures; 334.42 seconds |
| Frontend Node tests with RUN_AUTH_GATEWAY_TESTS=1 | **2 passed**, no skips; production Next.js server and mock backend exercised |
| Backend Ruff: app, services, AI, tests and migrations | Passed |
| Frontend ESLint: TypeScript, Hooks, accessibility and unsafe HTML/eval rules | Passed |
| Strict TypeScript: npm.cmd run typecheck | Passed |
| Next.js 16.3.8 production build | Passed; nonce-bearing pages render dynamically |
| Backend production wheel | Passed; current security/evaluation modules included and byte-checked against source; no deployment-secret files |
| Python compilation and offline Alembic migration SQL | Passed |
| Live MySQL migrations through 0009_dashboards | Passed on isolated test schema |
| Live Alembic schema-drift check | Passed: no new upgrade operations detected |
| npm audit, final frontend lock | Zero reported vulnerabilities, including development dependencies |
| pip-audit against backend/requirements.lock | No known vulnerabilities returned |
| Tracked private-key/cloud-key pattern check and git diff whitespace check | No matching tracked keys; whitespace check passed |

The reviewed wheel is in the ignored workspace `.runtime/security-build/reviewed/` directory; SHA-256 is `3227354a23906498e01322d61bcbc97fc066a2b4cf242d418c67cb36b9e42c90`. It is an API/AI package; provision the database with the repository's separately managed migrations. Synthetic test XML remains in the ignored `.runtime/security-build/` directory. The isolated MySQL server is shut down after verification.

The frontend test suite must run after `npm.cmd run build` with `RUN_AUTH_GATEWAY_TESTS=1`; otherwise its production-server integration test explicitly skips. Type checking is strict TypeScript `tsc --noEmit`; Python compilation is a separate syntax check, not a Python static type-analysis claim.

Dependency scans query the pinned backend lock with pip-audit and the frontend lock with npm audit. A clean result means no known advisory was returned at the audit date, not proof of freedom from vulnerabilities. Optional ML dependencies, platform-specific runtime dependencies, OS/container images and deployment infrastructure require their own scans.

## Logging and deployment requirements

Source review found no normal conversation-content application logging. Synthetic invalid-input/database-error tests capture logs and verify sensitive sentinels are absent. The isolated MySQL runtime was checked with general, slow-query and binary logging disabled; its error log contains operational startup/shutdown diagnostics. This does not establish how an institution's existing logs are configured.

Do not enable SQL parameter logging, HTTP payload tracing, provider-response logging, SMTP debug output or exception-local capture for participant workloads. Configure ingress/APM logs to omit request bodies, Authorization/Cookie values, email-link fragments, search queries and sensitive identifiers; use generated request IDs, status and timing for operations. Restrict access to audit metadata and set approved rotation/retention. Database backups and replication logs are sensitive data stores, not ordinary application logs.

Production requires TLS, explicit host/origin configuration, protected secret delivery and rotation, separate migration/runtime/export identities, storage/backup encryption, operational retention workers and tested restore/erasure procedures. The checked-in Compose setup uses reload and is a development configuration. Backend framework docs are not a substitute for network restrictions.

## Limitations and residual risks

- Staff MFA/SSO is not implemented. A stolen staff credential or overly broad authorized assignment remains a risk.
- Database operators and trusted export workers can bypass application RBAC if granted broad credentials. Protect and independently review those identities; exports are pseudonymous, not anonymous.
- Application throttles do not prevent distributed denial of service, slow uploads, oversized headers or malformed-request floods before routing. Add ingress body/header/time/concurrency limits. The backend does not trust arbitrary forwarded IP headers, so a shared Next/reverse-proxy IP shares its IP budget and may reduce availability; establish a reviewed trusted-proxy rate-limit design before institutional scale.
- Source-aware dashboard filtering may inspect all matching rows to count correctly. Large cohorts need bounded/materialized availability indexes and load testing.
- Expiry/soft hiding is not physical erasure. Raw-audio cleanup, database purge, export revocation, backup expiry and finite legal holds need institution-operated workflows. Owner privacy inventories intentionally retain limited metadata.
- The script CSP is strict; inline styles remain allowed for the existing UI. Tests inspect production HTTP output and script nonces; actual browser enforcement, hydration and assistive-technology behavior still need browser/device testing.
- Literal safety rules and output phrase checks are incomplete across languages, context and obfuscation. They cannot guarantee detection of crises or safe output from a deployed model. No continuous monitoring or emergency dispatch is promised.
- Real provider inference, SMTP delivery, public TLS, object-store controls, external log aggregation and Docker image builds were not validated locally. Docker is unavailable here. The backend wheel and Next production build do not constitute deployment approval.
- One SQLite-only MySQL-trigger case intentionally skips; real MySQL is required to validate immutable evidence/audit constraints. The current test-client library emits an upstream deprecation warning.
- ESLint 9 is development-only tooling selected for the accessibility plugin's declared compatibility; its support/deprecation status needs follow-up as that plugin adds newer ESLint compatibility. Do not ship development tooling in an institutional production runtime.

## Reference guidance

The logging choices follow [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html); request/access/rate boundaries were checked against [OWASP REST Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html). Browser header choices are informed by [OWASP HTTP Headers Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html), and nonce propagation/dynamic rendering use the [Next.js CSP guide](https://nextjs.org/docs/app/guides/content-security-policy). These references inform implementation, not a compliance claim.

## Follow-up personal access verification

New owner-only analysis/history and JSON download routes use existing authoritative access and retention checks. Counselor, administrator and other-student access is denied; withdrawal does not become a processing authorization. Downloads are bounded, rate-limited, no-store attachments and exclude privileged case notes, raw media and unavailable content. Eight additional SQLite/MySQL regression cases passed; the complete suite now has 631 passing cases and one expected SQLite skip. Frontend gateway tests verify server-derived ownership and Origin protection for fusion. Actual Edge browser checks cover student, counselor and administrator flows; these do not replace independent penetration, accessibility or production load testing.
