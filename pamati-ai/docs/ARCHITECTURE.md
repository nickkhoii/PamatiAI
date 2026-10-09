# PamatiAI architecture

PamatiAI: A Multimodal Conversational AI Framework for Student Mental Health and Sentiment Tracking.

## Scope and implementation status

This foundation runs a Next.js application, a FastAPI REST service, and MySQL 8.4 with utf8mb4. Implemented: live service status, readiness checking, validated configuration, SQLAlchemy connection lifecycle, 39 normalized database tables, explicit Alembic migrations, consent-aware persistence, database provenance/audit guards, development seed commands, deny-by-default authorization policy and automated database tests. Authentication, institutional onboarding, browser account forms, protected resource APIs and encrypted authentication email dispatch are implemented. Role workspaces, consent-aware inference, private in-app notifications and privacy request review are implemented. Physical privacy fulfillment and external domain notification delivery remain operational gaps. No clinical claims are made. See [DATABASE.md](DATABASE.md) for implemented persistence relationships and limitations.

## Components and boundaries

| Component | Responsibility and boundary |
| --- | --- |
| Student application | Accessible conversations, consent choices, history and data controls; own records only. |
| Counselor/reviewer portal | Assigned, consenting students; review indicators and record human decisions. |
| Administrator portal | Accounts, assignments, configuration and aggregate operations; no default content access. |
| Authentication service | Argon2id passwords, short-lived sessions, revocation; server establishes identity. Staff MFA/SSO remains planned. |
| Consent management | Versioned purpose-specific receipts; independent text, speech, visual and research choices; withdrawal gates pending work. |
| Conversation service | Persist consented messages, support-oriented replies; no medical advice. |
| Text analysis | Versioned pluggable sentiment/affect inference with uncertainty and provenance. |
| Speech analysis | Explicit opt-in acoustic processing (no transcription adapter bundled); delete raw audio by default after processing. |
| Optional visual analysis | Separate opt-in; disabled by default; no identity or psychiatric inference. |
| Multimodal fusion | Handle missing modalities explicitly; reported uncertainty (empirical calibration remains required); abstain when unsupported. |
| Longitudinal tracking | Student-relative trends with sample counts, windows, missingness and model-version boundaries. |
| Safety signaling | Conservative, reviewable support signals; never a diagnosis or autonomous clinical decision. |
| Human review | Assignment-scoped queue, acknowledgment and documented decisions; no automatic punitive actions. |
| Notifications | Current authorized record projections with owner-scoped read receipts; in-app only, no sensitive content or emergency dispatch. |
| Audit trail | Restricted append-only event records; metadata rather than conversation content. |
| Privacy tools | Owner inventories, hide/withdrawal, retention holds and export/erasure request review; full physical fulfillment and backups require verified institutional workers. |

## Data flow

Browser -> Next.js -> FastAPI -> SQLAlchemy -> MySQL. Analysis pipelines check consent and ownership before execution and recheck before publishing. Processing jobs preserve provenance; private notifications derive from current authorized records instead of copying case content. Authentication email uses an encrypted outbox. Separate object storage is planned for ephemeral encrypted media; media must never enter application logs.

Use opaque identifiers, UTC timestamps and ownership-carrying composite foreign keys. These persistence entities are now implemented; protected application endpoints and an authentication email dispatcher are implemented; inference execution is implemented; complete personal export/erasure fulfillment remains an operational gap. Analysis runs retain adapter version, model revision, preprocessing revision, modality availability, consent receipt, uncertainty and input lineage. Do not combine observations across changed model versions without documented validation.

## Authorization

STUDENT may access their own consent, conversation, history and privacy resources. COUNSELOR may access assigned student records only with an applicable active consent (no emergency override is implemented). ADMIN may manage accounts and configuration, but cannot read student content by default. The implemented policy enforces role, ownership, assignment and active consent independently; server-established bearer identity backs protected API routes. All new sensitive routes must authenticate first and apply resource policy server-side. See [AUTHENTICATION.md](AUTHENTICATION.md). Unknown permissions deny.

## Deployment and reproducibility

Docker Compose is a local development environment, not a production deployment. MySQL has no published host port. Migration runs precede backend readiness. Liveness does not depend on MySQL; readiness does and returns a sanitized 503 on failure. Production requires TLS, managed secrets, backups with tested restoration, monitored review staffing and security review before real student use.

Pin frontend dependencies in package-lock.json and Python dependencies in requirements.lock. Heavy ML libraries are optional; no models are downloaded at startup. Record model and dataset licenses, revisions, seeds, evaluation splits and hardware with each future experiment. Evaluate calibration, abstention, subgroup performance and temporal drift using scikit-learn; obtain research governance approval before collecting participant data.

References: [Next.js installation](https://nextjs.org/docs/app/getting-started/installation), [FastAPI containers](https://fastapi.tiangolo.com/deployment/docker/), [SQLAlchemy MySQL dialect](https://docs.sqlalchemy.org/en/20/dialects/mysql.html).

Student onboarding and informed consent are available at `/student/onboarding`; privacy controls and personal records are at `/student/privacy` and `/student/records`. See [privacy](PRIVACY.md) and [consent model](CONSENT_MODEL.md) for consent gates, retention policies and fulfillment boundaries.
