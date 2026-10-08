# PamatiAI

**A Multimodal Conversational AI Framework for Student Mental Health and Sentiment Tracking**

Production-oriented research prototype foundation for higher-education student support. PamatiAI performs sentiment/affect analysis and support-oriented risk signaling, NOT clinical diagnosis. It must not prescribe treatment or replace professionals or emergency services. AI indicators require authorized human oversight.

## What works now

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

Authentication, institutional onboarding, informed consent, student privacy views, protected student/counselor/administrator APIs and conversational message submission are implemented. A compatible HTTP model adapter is available with mocked validation; no real model deployment has been evaluated. Domain notifications, physical erasure/export fulfillment and full staff workspaces remain planned. Institutional governance and operational integrations must be validated before onboarding real participants.

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
../.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
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
