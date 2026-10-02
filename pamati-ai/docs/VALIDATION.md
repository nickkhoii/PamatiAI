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
