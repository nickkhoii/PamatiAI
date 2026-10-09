# PamatiAI

**A Multimodal Conversational AI Framework for Student Mental Health and Sentiment Tracking**

## 1. Overview

PamatiAI complements institutional student-support services. It is not a psychologist, psychiatrist, counselor, diagnostic system or emergency service. AI outputs are probabilistic research signals; human oversight remains essential.

## 2. Research purpose

Compare modalities, study personal affect patterns, and evaluate usability, conversation quality, latency, safety and human-review agreement. Software tests do not establish scientific or clinical validity.

**Not evaluated — labeled dataset required.** No real labeled dataset or empirical model-performance results are bundled.

## 3. Architecture

Browser -> Next.js cookie/Origin gateway -> FastAPI -> SQLAlchemy -> MySQL. Consent gates versioned analysis, personal trends and human review. Separate authorized workers produce research exports and reproducible evaluation reports.

Code is in `pamati-ai/`: `frontend/`, `backend/app/`, `backend/services/`, `ai/`, `database/migrations/`, `tests/`, and `docs/`. [Architecture](pamati-ai/docs/ARCHITECTURE.md).

## 4. Technology stack

Next.js 16, React 19, TypeScript, Tailwind CSS; Python 3.12+, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic; MySQL 8.4/InnoDB/utf8mb4; Argon2id; Pytest, Ruff, ESLint and Node HTTP tests. Dependencies are locked in frontend `package-lock.json` and backend `requirements.lock`.

## 5. Features

- Database-backed role dashboards with search, filters, pagination, UTC date ranges and loading/empty/error states.
- Onboarding, independent consent, withdrawal, chat/history, private check-ins and support requests.
- Text adapters, explicit audio/visual uploads, experimental fusion and personal trends.
- Contextual safety signals, human-review queue, append-only notes and referral choices.
- Private in-app notifications with persistent read receipts and current access checks.
- Configuration, institutional resources, audit trails, privacy request review and research evaluation.

[Requirements checklist and evidence](docs/FINAL_SYSTEM_AUDIT.md).

## 6. User roles

| Role | Access |
| --- | --- |
| STUDENT | Own conversations, consent, observations, check-ins, privacy and support |
| COUNSELOR | Active assigned students with current reviewer-access consent |
| ADMIN | Accounts, assignments, settings, audit and privacy-request metadata; no default conversation access |
| Research worker | Separately provisioned consent-aware offline export; no unrestricted researcher browser account |

AI-generated observations and human-reviewed assessments remain distinct. Staff role changes revoke sessions; removing counselor status revokes assignments.

## 7. Installation

Use Node.js 22+ (24 recommended), Python 3.12+, MySQL 8.4, or Docker Desktop/Engine. From repository root:

```powershell
cd pamati-ai
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock
cd frontend
npm.cmd ci
cd ..
```

Edit `.env` before starting. Never commit credentials or participant inputs. Windows execution policy may require `npm.cmd`.

## 8. Environment variables

The [complete template](pamati-ai/.env.example) defines database, authentication, SMTP, chat, analysis, fusion, tracking, safety and storage settings.

| Group | Main variables |
| --- | --- |
| Database | `DATABASE_URL`; Compose `MYSQL_DATABASE`, `MYSQL_USER`, distinct `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD` |
| Boundaries | `ENVIRONMENT`, `ALLOWED_HOSTS`, `CORS_ORIGINS`, `AUTH_PUBLIC_URL`, frontend `API_INTERNAL_URL` |
| Accounts/email | `PUBLIC_REGISTRATION_ENABLED=false`, `INSTITUTIONAL_DOMAINS`, token/session limits, Fernet `AUTH_DELIVERY_KEY`, `SMTP_*` with STARTTLS |
| Chat | `CONVERSATION_PROVIDER`, endpoint, model, model version and API key |
| Analysis | `TEXT_ANALYSIS_MODELS`, `AUDIO_ANALYSIS_ENABLED`, `VISUAL_ANALYSIS_ENABLED`, registered models and bounds |
| Fusion/tracking/safety | `MULTIMODAL_FUSION_*`, `LONGITUDINAL_*`, `SAFETY_POLICY`, `SAFETY_RESOURCES` |
| Privacy | `ALLOW_RAW_MEDIA_STORAGE=false`, private directories; retention periods and institutional raw gate are database settings |
| Development/testing | `DEV_SEED_PASSWORD` (16-128 characters), isolated `TEST_DATABASE_URL` ending `_test` |

JSON variables require valid JSON. URL-encode database passwords in native URLs; strong URL-safe passwords simplify Compose interpolation. Frontend connection variables are server-side. The backend loads `pamati-ai/.env`; native frontend variables must be set separately.

## 9. PostgreSQL setup and the actual database

**PostgreSQL is unsupported.** Existing migrations, triggers, constraints and upserts are MySQL-specific; settings reject PostgreSQL URLs. A port requires equivalent consent/audit guards and full dialect tests. The working MySQL implementation was preserved.

For native MySQL, provision a dedicated database and migration credential:

```sql
CREATE DATABASE pamati CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
```

Set `DATABASE_URL=mysql+pymysql://USER:URL_ENCODED_PASSWORD@127.0.0.1:3306/pamati?charset=utf8mb4`. Compose provisions the schema database and keeps its port private. Separate migration and runtime credentials in production. [Database guide](pamati-ai/docs/DATABASE.md).

## 10. Migrations

```powershell
# From pamati-ai/backend
$env:PYTHONPATH='.;..'
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m alembic current
..\.venv\Scripts\python.exe -m alembic check
```

Head: `0010_notifications`. Startup never creates tables. Back up and restore-test valuable databases before migration. MySQL DDL is not fully transactional; investigate failures before retrying or stamping.

## 11. Seed data

From backend: `..\.venv\Scripts\python.exe -m app.database_commands seed` provisions baseline roles, permissions and retention without fabricated conversations or totals.

For isolated development, securely set `DEV_SEED_PASSWORD`, then run the same command with `--development-accounts`. Accounts are `dev.student@pamati.example`, `dev.reviewer@pamati.example`, `dev.admin@pamati.example`. No default password exists. Seeds never reset passwords or pre-consent students and reject development accounts outside development. Assign counselors through administration after independent student consent.

The instance started during this audit has generated credentials in ignored `.runtime/integration/development.json`, field `development_password`. Never reuse them in production.

## 12. Running frontend

```powershell
# From pamati-ai/frontend
$env:API_INTERNAL_URL='http://127.0.0.1:8000'
$env:AUTH_PUBLIC_URL='http://localhost:3000'
$env:NEXT_TELEMETRY_DISABLED='1'
npm.cmd run dev
```

Open http://localhost:3000 and sign in. Dashboards: `/student`, `/counselor`, `/admin`. Backend authorization protects records even when a dashboard shell renders before sign-in.

## 13. Running backend

```powershell
# From pamati-ai/backend; configure DATABASE_URL first
$env:PYTHONPATH='.;..'
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --no-access-log --host 127.0.0.1 --port 8000
```

API docs: http://localhost:8000/docs. `/api/v1/health` checks liveness; `/api/v1/ready` checks MySQL; frontend `/api/status` checks both. Keep sensitive payloads, tokens and SQL parameters out of logs.

## 14. AI model configuration

| Pipeline | Default / capability |
| --- | --- |
| Conversation | `local-support`: predefined local replies, no LLM; approved `compatible-http` adapter available |
| Text | `[]`: disabled; registered `lexicon-baseline` is an unvalidated vocabulary comparator |
| Audio | Disabled; `acoustic-features`: mono 16-bit PCM WAV, 8-48 kHz, 30 seconds / 3 MB; no learned emotion model or transcription |
| Visual | Disabled; `no-expression`: bounded 24-bit BMP/JSON BMP frames, quality/abstention baseline; no learned expression recognition/general video decoder |
| Fusion | `late-fusion`; explicit eligible sources and provenance; weighted probability strategy requires compatible outputs |
| Tracking | `descriptive-personal-trends`; descriptive windows/gaps, no diagnostic cutoffs |
| Safety | Versioned contextual rules; false positives and missed signals possible |

The running audit instance enables lexicon, acoustic and no-expression development baselines; raw retention and research use remain off. Learned adapters need registration, pinned provenance, licensing, approval, evaluation and disclosure. Processor changes require renewed consent. [Text](pamati-ai/docs/TEXT_ANALYSIS.md), [audio](pamati-ai/docs/AUDIO_ANALYSIS.md), [visual](pamati-ai/docs/VISUAL_ANALYSIS.md), [fusion](pamati-ai/docs/MULTIMODAL_FUSION.md), [chat](pamati-ai/docs/CONVERSATION.md).

## 15. Testing

From `pamati-ai`: `.\scripts\check.ps1`. Optionally set an isolated MySQL `TEST_DATABASE_URL` ending `_test` first.

Runs backend/AI/authorization/consent/safety/evaluation tests, Ruff, migration SQL generation, frontend ESLint, production build, TypeScript and HTTP gateway tests. Without MySQL configuration, trigger-specific cases skip. Individual gateway tests require a built frontend and `RUN_AUTH_GATEWAY_TESTS=1`. Synthetic fixtures are not empirical evidence. [Final results](docs/FINAL_SYSTEM_AUDIT.md).

## 16. Docker

After configuring `pamati-ai/.env`, from repository root:

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

Order: database health -> migrations -> baseline seed -> API health -> frontend. Optional accounts: set `DEV_SEED_PASSWORD`, then `docker compose --profile development-accounts run --rm development-accounts`. `down` preserves volumes; avoid `down -v` on valuable data. Use Compose 2.24.4+ for the production overrides ([include](https://docs.docker.com/reference/compose-file/include/), [override](https://docs.docker.com/reference/compose-file/merge/)). [Deployment guide](docs/DEPLOYMENT.md).

## 17. Privacy controls

Students inspect inventories, read saved modality analyses, combine eligible sources, download their available personal records as JSON, hide conversations/check-ins, withdraw consent, request institutional export/erasure and see retention holds. Personal downloads exclude raw media, privileged case notes and unavailable source content. Administrators review request metadata without content access. **Request review does not physically export/erase all records and backups.** Verified institutional fulfillment remains required. [Privacy](pamati-ai/docs/PRIVACY.md).

## 18. Consent model

Versioned independent text/audio/visual/tracking/research/reviewer choices. Raw retention is separate and off by default; visual raw retention is unavailable. Consent is checked before processing and publication. Withdrawal cancels work and revokes new research use; it cannot undo processing or recall external copies. Holds extend retention without restoring processing permission. [Consent](pamati-ai/docs/CONSENT_MODEL.md).

## 19. Safety architecture

Supportive response constraints and rules produce AI observations for authorized contextual human review. Humans document decisions and offer configured referrals; students record choices. No autonomous diagnosis, treatment, punitive action, continuous monitoring or emergency dispatch. Configure genuine local resources and staffed response expectations. [Safety protocol](pamati-ai/docs/SAFETY_PROTOCOL.md), [ethics](pamati-ai/docs/ETHICAL_SAFEGUARDS.md).

## 20. Limitations

Learned emotion/visual models, clinical validity, staff SSO/MFA, external domain notification delivery and complete export/erasure/backup fulfillment remain outstanding. Authentication email requires STARTTLS SMTP and scheduling. Notifications project current records with source creation timestamps; state changes replace event keys. Browser/assistive-technology review, load testing, operational governance and real-adapter evaluation remain necessary. Compose validation does not prove container execution.

## 21. Research evaluation

From `pamati-ai`:

```powershell
.\.venv\Scripts\python.exe -m ai.evaluation ai/evaluation/manifest.template.json --output research-reports
```

Supports accuracy, precision/recall/F1, macro/weighted F1, confusion matrices, applicable ROC-AUC/calibration metrics, seven modality combinations and reproducible aggregate reports. Pseudonymous exports remain sensitive. Independent labels, participant-separated cohorts, calibration/fairness checks and prospective human-oversight validation are required. [Evaluation](pamati-ai/docs/EVALUATION.md), [research protocol](pamati-ai/docs/RESEARCH_PROTOCOL.md).

## 22. Deployment

[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) covers production images, HTTPS, secrets, staff bootstrap, SMTP/purge scheduling, backups and readiness. Passing software tests alone does not authorize student mental-health data collection.

## 23. Troubleshooting

| Symptom | Check |
| --- | --- |
| Readiness 503 | MySQL running, correct port/user/schema/charset, migrations, connectivity |
| Mutation 403 | Origin exactly matches `AUTH_PUBLIC_URL`; role/assignment/current consent valid |
| Session 401 | Sign in or renew through Account; security changes revoke sessions |
| Consent 409 | Reload current processor and retention disclosures |
| Empty trends | Adapter enabled, tracking consent, eligible observations, refresh saved trends |
| Upload rejected | Enabled processor/current consent; PCM WAV/BMP format and bounds |
| No email | Matching Fernet key, working STARTTLS SMTP, scheduled `app.auth_mail` |
| Import `ai` fails | `PYTHONPATH` includes backend and project parent |
| MySQL tests skip | Explicit isolated `TEST_DATABASE_URL` ending `_test` |
| Docker unavailable | Install/start Docker Desktop/Engine or use native setup |

Never paste private payloads, tokens or `.env` into logs. [Security audit](pamati-ai/docs/SECURITY_AUDIT.md), [final audit](docs/FINAL_SYSTEM_AUDIT.md).
