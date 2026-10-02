# PamatiAI architecture

PamatiAI: A Multimodal Conversational AI Framework for Student Mental Health and Sentiment Tracking.

## Scope and implementation status

This foundation runs a Next.js application, a FastAPI REST service, and MySQL 8.4 with utf8mb4. Implemented: live service status, readiness checking, validated configuration, SQLAlchemy connection lifecycle, 30 normalized database tables, explicit Alembic migrations, consent-aware persistence, database provenance/audit guards, development seed commands, deny-by-default authorization policy and automated database tests. Authentication, participant-facing data workflows, inference execution and notification dispatch remain planned. No student data is collected by exposed endpoints and no clinical claims are made by the foundation. See [DATABASE.md](DATABASE.md) for implemented persistence relationships and limitations.

## Components and boundaries

| Component | Responsibility and boundary |
| --- | --- |
| Student application | Accessible conversations, consent choices, history and data controls; own records only. |
| Counselor/reviewer portal | Assigned, consenting students; review indicators and record human decisions. |
| Administrator portal | Accounts, assignments, configuration and aggregate operations; no default content access. |
| Authentication service | Argon2id passwords, short-lived sessions, revocation, MFA for staff; server establishes identity. |
| Consent management | Versioned purpose-specific receipts; independent text, speech, visual and research choices; withdrawal gates pending work. |
| Conversation service | Persist consented messages, support-oriented replies; no medical advice. |
| Text analysis | Versioned pluggable sentiment/affect inference with uncertainty and provenance. |
| Speech analysis | Explicit opt-in transcription and acoustic processing; delete raw audio by default after processing. |
| Optional visual analysis | Separate opt-in; disabled by default; no identity or psychiatric inference. |
| Multimodal fusion | Handle missing modalities explicitly; calibrated uncertainty; abstain when unsupported. |
| Longitudinal tracking | Student-relative trends with sample counts, windows, missingness and model-version boundaries. |
| Safety signaling | Conservative, reviewable support signals; never a diagnosis or autonomous clinical decision. |
| Human review | Assignment-scoped queue, acknowledgment and documented decisions; no automatic punitive actions. |
| Notifications | Transactional outbox, retries and deduplication; no sensitive content in email or push. |
| Audit trail | Restricted append-only event records; metadata rather than conversation content. |
| Privacy tools | Access/export, withdrawal, retention and deletion including derived outputs and backups. |

## Data flow

Browser -> Next.js -> FastAPI -> SQLAlchemy -> MySQL. Future inference workers receive pseudonymous jobs only after consent and ownership validation, and recheck consent before publishing outputs. Transactional outbox records work and notifications alongside domain changes. Separate object storage is planned for ephemeral encrypted media; media must never enter application logs.

Use opaque identifiers, UTC timestamps and ownership-carrying composite foreign keys. These persistence entities are now implemented; queue workers and application endpoints remain planned. Analysis runs retain adapter version, model revision, preprocessing revision, modality availability, consent receipt, uncertainty and input lineage. Do not combine observations across changed model versions without documented validation.

## Authorization

STUDENT may access their own consent, conversation, history and privacy resources. COUNSELOR may access assigned student records only with an applicable active consent or a separately documented institution-approved emergency legal basis. SYSTEM_ADMINISTRATOR may manage accounts and configuration, but cannot read student content by default. The implemented policy enforces role, ownership, assignment and active consent independently; it is not an authentication endpoint. All future routes must authenticate first and apply resource policy server-side. Unknown permissions deny.

## Deployment and reproducibility

Docker Compose is a local development environment, not a production deployment. MySQL has no published host port. Migration runs precede backend readiness. Liveness does not depend on MySQL; readiness does and returns a sanitized 503 on failure. Production requires TLS, managed secrets, backups with tested restoration, monitored review staffing and security review before real student use.

Pin frontend dependencies in package-lock.json and Python dependencies in requirements.lock. Heavy ML libraries are optional; no models are downloaded at startup. Record model and dataset licenses, revisions, seeds, evaluation splits and hardware with each future experiment. Evaluate calibration, abstention, subgroup performance and temporal drift using scikit-learn; obtain research governance approval before collecting participant data.

References: [Next.js installation](https://nextjs.org/docs/app/getting-started/installation), [FastAPI containers](https://fastapi.tiangolo.com/deployment/docker/), [SQLAlchemy MySQL dialect](https://docs.sqlalchemy.org/en/20/dialects/mysql.html).
