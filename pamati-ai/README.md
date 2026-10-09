# PamatiAI

**A Multimodal Conversational AI Framework for Student Mental Health and Sentiment Tracking**

Production-oriented research prototype foundation for higher-education student support. PamatiAI performs sentiment/affect analysis and support-oriented risk signaling, NOT clinical diagnosis. It must not prescribe treatment or replace professionals or emergency services. AI indicators require authorized human oversight.

## What works now

Offline empirical evaluation in `ai/evaluation/` supports single-label/multilabel
metrics, explicitly applicable probability/calibration metrics, seven modality
variants, paired cohorts and seeded group-bootstrap uncertainty, measured system
observations, and reproducible aggregate experiment artifacts. The separate
consent-aware research worker exports pseudonymous derived observations without
raw inputs or identities. No real labeled evaluation dataset is bundled and no
model-performance results are claimed. See [EVALUATION](docs/EVALUATION.md) and
[RESEARCH_PROTOCOL](docs/RESEARCH_PROTOCOL.md).

Role dashboards are available at `/student`, `/counselor` (also `/reviewer`), and
`/admin`. Apply migration `0009_dashboards` with `alembic upgrade head` from
`backend` before starting an existing installation. All lists and totals come
from the database; unpopulated databases show empty states.

Students can search recent conversations, visualize saved experimental trends,
record optional private well-being check-ins, manage consent and privacy, request
human support, and browse institutional resources. Check-ins are self-reports,
never analyzed or scored by AI. They use the conversation retention period,
are included in the personal privacy inventory and retention-review report, and
can be hidden independently of AI consent. Export/deletion requests still require
institutional fulfillment, including check-ins.

Counselors see only active assigned students with current reviewer-access consent.
Their workspace separates **AI-generated observations** from **human-reviewed
assessments**, with risk-source context, append-only review notes, referral offers,
and support-request acknowledgement/closure. Saved trends can be refreshed using
the existing consent-aware longitudinal workflow.

Administrators can search users, change roles/account activation, assign or revoke
counselors, inspect role permissions and registered model configuration, edit
supported system/retention settings, read audit logs, and maintain database-backed
institutional resources. Model version records are immutable research provenance;
runtime model selection remains in deployment configuration and requires
redeployment. The institutional resource editor accepts a JSON `resources` array
of `{id, label, description, url}` entries. Safety contacts and referral services
remain governed by the existing validated safety deployment configuration.

Lists support search, applicable status filters, inclusive UTC date ranges, and
pagination. The UI includes responsive navigation, labeled forms, table captions,
keyboard focus, accessible trend history, and loading/empty/error states. Browser
mutations use the existing HTTP-only bearer-cookie bridge and Origin checks;
backend authorization remains authoritative.

Optional visual research architecture provides bounded image/frame sampling, replaceable
observable-expression adapters, consent checks and temporary cleanup. It defaults to
disabled, retains no raw images/video, and does not restrict text support when declined.
See [VISUAL_ANALYSIS](docs/VISUAL_ANALYSIS.md) for scope and scientific limitations.

Optional audio research analysis supports bounded WAV uploads, acoustic feature summaries,
replaceable emotion adapters and independent raw-retention controls. It defaults to disabled
and requires separate informed audio consent. See [AUDIO_ANALYSIS](docs/AUDIO_ANALYSIS.md).

Modular text analysis supports multiple configured research models per student message,
normalized sentiment/affect outputs, uncertainty and traceable database records.
It is disabled by default; enable the offline comparator or register a reviewed adapter
using [TEXT_ANALYSIS](docs/TEXT_ANALYSIS.md).

Student chat at `/student/chat` includes conversation history, accessible text composition, consent status, privacy/settings links and human-support requests. The default uses local predefined support responses; a modular model adapter is available. Apply migration `0007_conversation` before launch. See [conversation behavior and provider configuration](docs/CONVERSATION.md).

Next.js/React/TypeScript/Tailwind shell with real service status; FastAPI liveness and database readiness; normalized MySQL utf8mb4 schema with 37 domain/authentication tables; SQLAlchemy models and explicit Alembic migrations; consent-aware persistence helpers and database guards; Argon2id development seeds; tested least-privilege authorization policy; pluggable analysis pipelines; Docker development services and dependency locks.

Experimental multimodal fusion combines explicitly selected, consented analysis records through the API, with late fusion, compatible weighted probability fusion and a learned-strategy interface. See [MULTIMODAL_FUSION](docs/MULTIMODAL_FUSION.md) for configuration, provenance and scientific limitations.

Longitudinal tracking provides interaction, daily and weekly summaries, rolling personal baselines, trajectories and configurable experimental change indicators. Student records and assigned reviewer trend views show gaps and uncertainty without diagnostic scores. See [LONGITUDINAL_ANALYSIS](docs/LONGITUDINAL_ANALYSIS.md) for mathematical definitions, consent and configuration.

Consented chat now routes configured explicit safety-language concerns to immediate local supportive guidance and a human-review workflow. Assigned reviewers use `/reviewer/safety`; students can view documented support offers. Apply database migration `0008_safety_workflow` before running against an existing database. See [SAFETY_PROTOCOL](docs/SAFETY_PROTOCOL.md) for policies, contact configuration, permissions and limitations.

Authentication, institutional onboarding, informed consent, student privacy views, protected student/counselor/administrator APIs and conversational message submission are implemented. A compatible HTTP model adapter is available with mocked validation; no real model deployment has been evaluated. Domain notifications and physical erasure/export fulfillment remain planned. Institutional governance and operational integrations must be validated before onboarding real participants.

## Docker development

Requires Docker Engine with Compose v2 (Docker Desktop on Windows).

```powershell
cd pamati-ai
Copy-Item .env.example .env
# Edit .env: choose distinct passwords using URL-safe alphanumeric characters.
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

Open http://localhost:3000. API docs: http://localhost:8000/docs. Liveness: `/api/v1/health`; readiness: `/api/v1/ready`. The migration job completes before backend startup. Database readiness returns 503 if MySQL is inaccessible. Use `docker compose logs -f` for troubleshooting and `docker compose down` to stop while preserving data. Source changes in frontend/src and backend/app reload automatically.

## Local development

Requires Node.js 22+ (24 recommended), Python 3.12+ and an accessible MySQL 8.4 instance if readiness or migrations are needed. No database is required for liveness, frontend builds or unit tests.

```powershell
cd pamati-ai
Copy-Item .env.example .env
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.lock
cd backend
$env:PYTHONPATH = (Resolve-Path ..).Path
../.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000 --no-access-log
```

In a separate terminal:

```powershell
cd pamati-ai/frontend
npm.cmd ci
npm.cmd run dev
```

The frontend server defaults to http://127.0.0.1:8000; set API_INTERNAL_URL in frontend/.env.local to override. Backend loads pamati-ai/.env when run from backend/. The root environment is automatically used by Compose. The UI reports database unavailable until a configured MySQL instance responds.

## Checks and migrations

```powershell
cd pamati-ai/backend
../.venv/Scripts/python.exe -m pytest
../.venv/Scripts/python.exe -m ruff check app ../tests/backend
../.venv/Scripts/python.exe -m alembic upgrade head
../.venv/Scripts/python.exe -m app.database_commands seed
cd ../frontend
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
```

The Python lock includes development tooling for this research foundation. Update it deliberately using `uv pip compile backend/pyproject.toml --extra dev --python-version 3.12 -o backend/requirements.lock`. Commit frontend/package-lock.json after intentional dependency updates. Optional heavy ML dependencies are declared in backend/pyproject.toml but excluded from the base lock.

Architecture and implementation boundaries: [ARCHITECTURE](docs/ARCHITECTURE.md), [DATABASE](docs/DATABASE.md), [SECURITY](docs/SECURITY.md), [AI_SAFETY](docs/AI_SAFETY.md). DATABASE includes initialization, explicit development-account seeds and real-MySQL tests. See docs/VALIDATION.md for checks run in the creation environment and remaining verification.

Authentication and role-based access: see [deployment and API instructions](docs/AUTHENTICATION.md). Start browser account flows at `/auth/login`.

Student onboarding and informed consent are available at `/student/onboarding`; privacy controls and personal records are at `/student/privacy` and `/student/records`. See [privacy](docs/PRIVACY.md) and [consent model](docs/CONSENT_MODEL.md) for consent gates, retention policies and fulfillment boundaries.

The [security audit](docs/SECURITY_AUDIT.md) records verified defenses, abuse tests and residual risks. [Ethical safeguards](docs/ETHICAL_SAFEGUARDS.md) explains participant agency, human oversight and research limits. Run `scripts/check.ps1` for backend tests, lint, migration SQL, frontend lint, strict TypeScript, production build and the production gateway tests. Production requires TLS and explicit approved hosts/origins; the development Compose configuration is not a production launch setup.
