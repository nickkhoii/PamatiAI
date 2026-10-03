# Student conversation

The student interface at `/student/chat`, linked from Profile, includes a responsive sidebar, new conversations, private history, paginated messages, a labeled composer, consent status, support requests and settings/privacy links. Enter sends; Shift+Enter adds a line; input-method composition is preserved. Drafts stay in memory rather than browser storage. Provider text renders as escaped plain text, without executing HTML or Markdown. Audio, visual, tracking and research choices are independent of chat, and no camera or microphone is activated.

## Provider configuration

`backend/services/conversation/` contains the provider protocol, typed `Reply`, factory, response guard and versioned system prompt in `prompt.py`. Generation is separate from sentiment inference, longitudinal tracking and research: sending messages invokes none of those pipelines.

The default `local-support` provider is a deterministic predefined support baseline, **not an LLM or sentiment model**. It makes no external requests. The UI identifies these responses explicitly. It covers general reflection, study pressure and campus guidance without inventing contacts or promising staff response. This baseline is limited and repetitive and should not be presented as a clinical intervention.

The optional `compatible-http` adapter supports a deployment-approved chat-completions compatible server, including local models. Configure process environment variables:

```dotenv
CONVERSATION_PROVIDER=compatible-http
CONVERSATION_ENDPOINT=http://127.0.0.1:8080/v1/chat/completions
CONVERSATION_MODEL=your-model-identifier
CONVERSATION_MODEL_VERSION=your-pinned-model-revision
CONVERSATION_API_KEY=
```

Only HTTPS or loopback HTTP is accepted. URLs cannot contain credentials or query secrets. Endpoint configuration is server-owned; redirects and environment proxies are disabled. The adapter sends the system prompt and up to 20 recent text messages from the same authorized conversation. It sends no account identifiers, other conversations, audio, images or research/trend records. Timeouts, malformed/empty/oversized output and guard failures produce an identified local fallback. There are no automatic provider retries. Response downloads are capped at 64 KiB and published text at 6,000 characters.

Before using a remote host with participant data, the institution must review processing location, retention, training use and contractual safeguards and adapt disclosures where needed. Provider, host, requested model and deployment version are captured in consent snapshots. Changing them or the endpoint fingerprint requires new acknowledgment before text submission; secrets are excluded. Policy `2026-10-03.2` adds this disclosure, so existing students review their choices again. Model revision is declared by the operator; the returned model identifier is stored when reported. Pin and independently verify revisions for reproducible evaluations.

## Safety

The system prompt identifies PamatiAI as AI, forbids human impersonation, diagnoses and “I know exactly how you feel,” and directs empathetic, non-deceptive support and appropriate human help. A server guard rejects known prohibited assertions and invalid output. Explicit English danger phrases use local emergency guidance without calling a provider. This keyword path is not reliable distress detection across languages or contexts. It neither alerts staff nor dispatches help. Help requests are durable institutional queues without guaranteed response time.

Prompts and phrase guards cannot guarantee arbitrary model behavior. Before enabling a model for students, evaluate paraphrased diagnostic claims, prompt injection, cultural/language coverage, misleading reassurance, invented campus contacts and emergency scenarios. Maintain qualified human oversight and monitoring. No third-party model is enabled by default.

## API and persistence

Apply `alembic upgrade head` from `backend` before launching. Migration `0007_conversation` adds nullable message request IDs and generation metadata without rewriting existing content.

| Endpoint | Behavior |
| --- | --- |
| `GET /api/v1/students/{student_id}/conversations` | Authorized history, up to 100 conversations |
| `POST /api/v1/students/{student_id}/conversations` | Owner creates a consent-gated conversation |
| `GET /api/v1/conversations/{id}?offset=0&limit=100` | Newest page in display order; `next_offset` retrieves earlier messages |
| `POST /api/v1/conversations/{id}/messages` | Owner submits `{request_id: UUID, text: string}` and receives student/assistant messages |
| `DELETE /api/v1/conversations/{id}` | Owner hides history; this is not erasure |

Backend authorization is authoritative. Admin status grants no conversation access. Assigned counselors with current reviewer-access permission may read, but cannot send as students. The cookie gateway checks Origin and derives ownership from the backend session; tokens stay in HttpOnly cookies. Backend account, ownership, consent and conversation checks are independent of the UI.

User/conversation locks serialize turn reservation and sequence assignment. A unique request UUID enables idempotent replay; different text or conversations with the same UUID are rejected. Student input and a pending assistant slot commit before generation, without holding database locks across provider calls. Concurrent sends to the same conversation are rejected while pending. Stale pending slots recover with a local fallback after 60 seconds. Consent, processor configuration and conversation availability are checked again before publication. Changed consent discards generated text and leaves status/provenance evidence. Withdrawal cannot undo text already processed by a configured provider.

Responses record consent receipt ID, prompt version, provider, model, deployment/model version and completed/fallback/discarded status. Audits contain actions and identifiers, never message content or provider exceptions. Existing ownership foreign keys and retention snapshots apply. Production requires HTTPS, restricted database credentials and encrypted volumes/backups. Do not enable MySQL general-query logging against student data.

## Validation

Automated tests cover cross-user/staff write denial, disabled text consent, text-only chat with optional choices off, idempotency, pending recovery, consent/account/conversation changes during generation, provider failures, unsafe output, input limits, processor changes and history pagination. HTTP adapter tests use mocked transport, never a real model. Gateway integration uses a real Next.js production server and mocked backend to verify chat routes, Origin, cookie handling and rendered accessibility markup. Interactive browser/screen-reader evaluation remains a deployment validation task.
