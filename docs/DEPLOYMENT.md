# Deployment

PamatiAI complements institutional student support. It is a nonclinical research framework with probabilistic AI signals and essential human oversight. Passing implementation checks is not approval to recruit participants.

## Local/research Compose

Install Docker Desktop/Engine and Compose 2.24.4+; configure `pamati-ai/.env` from `.env.example` with distinct strong URL-safe database passwords. From repository root:

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

The root file includes the canonical project Compose file. Relative build/bind paths stay within `pamati-ai`. Startup is MySQL health -> Alembic -> baseline seed -> API health -> frontend. Migration and seed services exit successfully; that is expected. MySQL has a private internal network and persistent volume; only frontend/API ports are published to host loopback. Frontend: http://localhost:3000. API: http://localhost:8000/docs. These commands are for a Docker-capable host: this audit validated configuration, not container execution.

For development accounts, set a private process `DEV_SEED_PASSWORD` of 16-128 characters and run:

```powershell
docker compose --profile development-accounts run --rm development-accounts
```

The student, reviewer and admin emails are in the root README. Never pre-consent students or use these accounts with participants. Existing passwords are not reset on repeat seed. An administrator must assign the reviewer and the student must permit reviewer access.

```powershell
docker compose logs --tail 100 backend frontend migrate seed
docker compose down
```

Stopping preserves volumes. Never issue `down -v` against valuable data. Keep payloads, secrets and participant identifiers out of shared diagnostics.

## Native development

Follow root README sections 7-15. The audit started an isolated MySQL database `pamati_integration` at 127.0.0.1:3307, API at 127.0.0.1:8000 and frontend at localhost:3000. Private generated credentials, process IDs and validation artifacts are in ignored `.runtime/integration/`. This environment uses local research baselines and synthetic workflow inputs, not real student data. The database credential has schema administration privileges for development; it must not be reused in production.

To stop this audit instance, inspect `.runtime/integration/processes.json` and verify each PID still belongs to the expected Uvicorn/Next process before stopping it. Stop the matching services first. Shut MySQL down through its administrative connection only after verifying `@@datadir` matches `.runtime/mysql/data`; avoid terminating an unrelated database instance. For restart, use the root README commands with the local private database configuration and the same baseline settings.

## Production configuration

Use a separately approved host, secrets and participant database. From `pamati-ai`, configure a private `.env.production` and validate:

```powershell
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml config --quiet
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml up --build -d
```

The override forces production backend settings, removes reload and source binds, and uses the dedicated frontend production image. It requires Compose `!override`/`!reset` support; see [Docker merge documentation](https://docs.docker.com/reference/compose-file/merge/). Root inclusion behavior is defined in [Docker include documentation](https://docs.docker.com/reference/compose-file/include/).

Set `ENVIRONMENT=production`, `AUTH_PUBLIC_URL=https://YOUR_APPROVED_HOST`, explicit HTTPS `CORS_ORIGINS` and explicit `ALLOWED_HOSTS` including the internal backend/healthcheck hosts. Set frontend `API_INTERNAL_URL` to the private backend. Configure a reverse proxy for public HTTPS to the loopback frontend, valid certificates, request limits, timeouts and redacted logs. Do not publish MySQL or directly expose the development HTTP API. Validate Secure cookies, Origin checks, per-request CSP nonces and HSTS through the actual proxy. Do not enable the development-accounts profile; production seeds reject development accounts.

The Compose credential is intentionally shared with migration/seed for local research convenience. For production, deploy migrations/seed as separate controlled jobs using DDL credentials; replace the API and operations worker URLs with separately limited runtime credentials using the grants in [DATABASE.md](../pamati-ai/docs/DATABASE.md). Do not grant the API permission to rewrite audit/consent evidence. Pin reviewed image digests, scan final images, encrypt data/backups, restrict host/service access and resource use, and rotate credentials under an approved incident procedure. No PostgreSQL support is claimed.

## Institutional bootstrap and email

Provision the first real administrator with process-only `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD`, `BOOTSTRAP_ADMIN_NAME`, then run `python -m app.bootstrap_admin` inside a controlled backend job. It refuses to modify existing accounts or replace an existing administrator. Invite subsequent staff through the authorized account API.

Generate a Fernet key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` in a private terminal and put it in approved secret storage. The API and dispatcher must share `AUTH_DELIVERY_KEY`. Configure a genuine `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM` and applicable credentials. SMTP always requires STARTTLS. Authentication outbox delivery is a one-shot job, not a continuously running scheduler:

```powershell
docker compose --profile operations run --rm auth-mail
docker compose --profile operations run --rm purge-audio
```

Use the same production override/env-file flags for production jobs. Schedule dispatcher runs and expired-audio purge with a restricted institutional scheduler, monitor failures without payload logging, and validate delivery/physical deletion. The purge job removes eligible stored audio; it does not erase every database category or backup. Domain support notifications are private **in-app only**; they do not send emergency messages, email or push.

## Consent, models and safety

The default chat uses local predefined replies. Text analysis is off; audio and visual are off; raw retention is off. Enable registered adapters only after review, version pinning, licensing and scientific evaluation. Current acoustic/no-expression adapters are quality/abstention baselines, not learned emotion recognition. Processor changes require renewed student disclosures/consent. Optional uploads never activate microphones or cameras.

Configure genuine institutional resources through the admin dashboard and validated safety/referral resources through deployment settings. Define staffed review times, escalation responsibilities and non-AI ways to request help. Risk observations and professional assessments remain distinct. There is no continuous monitoring or automatic emergency dispatch.

## Retention, backups and readiness

Approve periods and documented finite holds. Schedule retention reports (`python -m app.retention_report`) and validate separately authorized export/erasure fulfillment before participants use the system. The current API records and reviews requests but does not certify full physical erasure or personal export completion. Audit/consent evidence guards mean a broad deletion script is inappropriate. Encrypt backups, test restoration, reapply withdrawal/deletion decisions before restoring access, and document external dataset recall and backup expiry.

Check API liveness `/api/v1/health`, database readiness `/api/v1/ready`, and frontend `/api/status`. Run migration drift checks and the complete suite with a dedicated MySQL `_test` schema before release. Verify login/refresh/logout, onboarding/withdrawal, denied cross-student/admin/unassigned access, each enabled modality, human review, referral choice, notifications and privacy request review through the deployed gateway.

Release gates still include Docker image execution, live SMTP, actual HTTPS/proxy behavior, browser/assistive-technology review, operational privacy fulfillment, institution-approved resources/ethics and real labeled model evaluation. Do not describe this prototype as a completed clinical or participant-ready system.
