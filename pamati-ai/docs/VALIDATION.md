# Foundation validation

Validated on 2026-10-02 on Windows with Node.js 24.19.0 and workspace-local Python 3.12.14.

| Check | Result |
| --- | --- |
| Backend Pytest | 12 passed: liveness, readiness success/failure, host rejection and role/resource denial boundaries |
| Ruff | Passed |
| AI and migration Python compilation | Passed |
| Alembic `upgrade head --sql` | Passed; generated MySQL baseline SQL |
| Frontend status-response test | Passed for available, 503, network failure and unexpected payload |
| Next.js production build | Passed |
| TypeScript check | Passed |
| npm dependency audit at installation | Zero reported vulnerabilities |
| Live Uvicorn startup | Passed; health HTTP 200, readiness HTTP 503 without MySQL |
| Live Next.js production startup | Passed; homepage HTTP 200, X-Frame-Options DENY |
| Frontend-to-backend status route | Passed; API available, database unavailable |
| Compose YAML parsing | Passed with PyYAML |
| Docker image builds and Compose startup | Not run: Docker executable unavailable |
| Live MySQL migration and utf8mb4 round-trip | Not run: MySQL unavailable |

Pytest emits an upstream Starlette deprecation warning concerning its httpx test-client integration. Tests pass; monitor this when refreshing dependencies.

Before accepting the integrated development environment on a Docker-equipped machine, run `docker compose config --quiet`, `docker compose up --build -d`, and `docker compose ps`. Confirm migrate exits zero, backend and frontend become healthy, `/api/v1/ready` returns 200 and `/api/status` reports both services available. Test an emoji round-trip against the future schema when student-data migrations are introduced. These steps are not represented as already completed.

No browser automation or manual assistive-technology review was performed. The frontend includes semantic landmarks, heading hierarchy, a skip link, visible keyboard focus and an announced status region, but full accessibility validation remains required before participant use.
