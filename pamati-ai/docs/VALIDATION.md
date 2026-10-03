# Foundation and database validation

Validated on 2026-10-02 on Windows with Node.js 24.19.0, workspace-local Python 3.12.14 and an isolated MySQL 8.4.4 runtime. MySQL binds only to 127.0.0.1:3307; its files and generated credentials are in the ignored workspace `.runtime/mysql` directory. No Windows service was installed. The test server is stopped after validation.

| Check | Result |
| --- | --- |
| Backend Pytest | 44 passed: 12 foundation tests and 32 real-MySQL persistence/security tests; TEST_DATABASE_URL explicitly enabled |
| Ruff | Passed |
| AI and migration Python compilation | Passed |
| Alembic `upgrade head --sql` | Passed; generated MySQL baseline SQL |
| Live MySQL migrations | Passed through 0004_evidence_integrity; full downgrade to base and re-upgrade passed |
| Alembic schema drift | Passed: no new upgrade operations detected |
| Initialization/seed CLI | Passed: database initialization, roles, explicit development accounts and repeat seed |
| Schema encoding | All 30 domain tables use utf8mb4_0900_ai_ci; emoji and non-Latin message round-trip passed |
| Database constraints/triggers | Passed: ownership, consent supersession/withdrawal, immutable provenance, inference timestamps, optional modalities, reviewer assignment, raw-media gates/expiry and audit append-only behavior |
| Frontend status-response test | Passed for available, 503, network failure and unexpected payload |
| Next.js production build | Passed |
| TypeScript check | Passed |
| npm dependency audit at installation | Zero reported vulnerabilities |
| Live Uvicorn startup | Passed; health HTTP 200, readiness HTTP 503 without MySQL |
| Live Next.js production startup | Passed; homepage HTTP 200, X-Frame-Options DENY |
| Frontend-to-backend status route | Passed; API available, database unavailable |
| Compose YAML parsing | Passed with PyYAML |
| Docker image builds and Compose startup | Not run: Docker executable unavailable |

Pytest emits an upstream Starlette deprecation warning concerning its httpx test-client integration. Tests pass; monitor this when refreshing dependencies.

Before accepting the integrated development environment on a Docker-equipped machine, run `docker compose config --quiet`, `docker compose up --build -d`, and `docker compose ps`. Confirm migrate exits zero, backend and frontend become healthy, `/api/v1/ready` returns 200 and `/api/status` reports both services available. These Compose steps are not represented as already completed; database migration execution has been validated independently on live MySQL.

Without TEST_DATABASE_URL, the 32 integration tests skip explicitly and foundation tests still run. See [DATABASE.md](DATABASE.md) for the isolated `_test` database requirement and seed commands. Downgrades were exercised only on the disposable test schema, never on participant data.

No browser automation or manual assistive-technology review was performed. The frontend includes semantic landmarks, heading hierarchy, a skip link, visible keyboard focus and an announced status region, but full accessibility validation remains required before participant use.

## Authentication/RBAC validation ? 2026-10-03

Implemented migration 0005_authentication and validated against a separate workspace-local `pamati_auth_test` MySQL 8.4.4 database. No participant schema or real `.env` was changed. The full backend run passed 124 tests: 40 authentication tests on each of SQLite and MySQL, 12 foundation tests and 32 MySQL persistence tests. Two subsequently added logout/delivery tests passed on both databases; affected logout tests were also rerun. Ruff and offline migration SQL generation passed. Live migration upgrade through 0005 passed and Alembic reported no schema drift.

The frontend production build and TypeScript check passed. The two Node tests passed with `RUN_AUTH_GATEWAY_TESTS=1`: the existing status test plus an actual Next.js production gateway test against a mock backend. It checks rejected cross-origin mutations, HttpOnly/Secure/SameSite cookie attributes, removal of tokens from browser response bodies, bearer forwarding, refresh cookie authority and logout after access expiry. It does not claim real SMTP delivery or end-to-end browser automation.

Run the gateway test after a production build:

```powershell
npm.cmd run build
$env:RUN_AUTH_GATEWAY_TESTS = '1'
try { npm.cmd test } finally { Remove-Item Env:RUN_AUTH_GATEWAY_TESTS }
```

Without TEST_DATABASE_URL, SQLite authorization tests still run; MySQL persistence tests explicitly skip. The optional authentication MySQL fixture requires an isolated `_test` database and the current migrations. SMTP sending is implemented but not exercised against a real provider; configure delivery and schedule the dispatcher before enabling onboarding/recovery.

## Student consent and privacy validation ? 2026-10-03

Migration 0006_consent_privacy was applied to the isolated `pamati_auth_test` MySQL 8.4.4 database. A downgrade to 0005 and re-upgrade succeeded, including retention defaults and new evidence guards; Alembic reported no schema drift. The real `.env` and participant schemas were not changed.

The full backend run passed 179 tests with one intentional SQLite skip for MySQL-only disclosure/manifest triggers. Subsequent retention-version changes and added cached-receipt regressions were checked with 63 passing affected consent/authorization cases (one MySQL-trigger skip), then eight passing cached-receipt/withdrawal cases across SQLite and MySQL. Tests verify false optional defaults, independent modality gates before adapter execution, exclusion of disabled fusion inputs, withdrawal during adapter execution, current consent over cached ORM state, timestamp/version/disclosure evidence, immutable snapshots, retention conflicts, raw-expiry caps, independent research/tracking permission, owner-only personal views and finite transparent holds. Ruff and offline migration SQL generation passed.

Next.js production build, TypeScript and the two Node tests passed. The production gateway test additionally checks server-derived student identity despite a client-supplied owner query, PUT forwarding for consent, DELETE forwarding for withdrawal, and preservation of explicitly false optional fields. Real model execution, recording devices, SMTP delivery, physical erasure across storage/backups and completed export fulfillment are not claimed as validated.

Student pages: `/student/onboarding`, `/student/privacy`, `/student/records`. Apply current migrations before running the backend. Retention settings default to documented example limits; institutions must approve actual periods and hold procedures before participant onboarding. `python -m app.retention_report` prints aggregate due/held counts and does not delete records.
