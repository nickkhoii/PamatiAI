# Consent model and processing boundary

## Consent dimensions

| Persisted field | Permission | Dependency |
| --- | --- | --- |
| text_processing | Text sentiment/affect analysis and conversational AI | Explicit choice; not required to access privacy/support |
| audio_processing | Audio analysis | Optional; does not grant raw storage or activate capture |
| visual_processing | Visual analysis | Optional; no identification/clinical inference or raw storage grant |
| longitudinal_tracking | Derived observations and personal trend aggregation | Independent of modality permission; source inference must be completed and owned |
| research_data_use | Approved research membership/use | Independent; ethics approval and de-identification provenance still required |
| reviewer_access | Assigned counselor access | Independent; active assignment and current consent also required |
| retain_audio / retain_visual | Retain corresponding raw samples | Corresponding analysis permission, environment gate, database gate and configured expiry cap |

New choices default false. There is no all-enabled switch, preselected optional grant, countdown, guilt message or disadvantage to declining optional features. The three onboarding steps can be revisited directly. “Save these choices” and “Continue without AI analysis” have equal visual prominence. A separate acknowledgement confirms review of the disclosures; it never toggles an analysis flag. Raw retention is always false in the onboarding submission.

## Evidence and versioning

`ConsentRecord` is student-owned, uniquely versioned per student, and records `created_at` in UTC. `policy_version` identifies the immutable disclosure wording in `app.consent_policy`. HTTP consent changes require the current disclosure version, the displayed retention version and a true acknowledgement. Saving after a retention configuration change returns 409 so the student can review new information before consenting. `disclosure_snapshot` preserves all disclosure sections and the displayed versioned retention policy. The client submits `expected_version` to detect stale edits; the server locks the student and compares it with the latest receipt before appending.

Every save appends a receipt containing the full set of choices; omitted permissions default false rather than silently inheriting older grants. The highest version is authoritative even when withdrawn. Old receipts never regain authority after withdrawal. Existing MySQL guards prohibit alteration/deletion of receipts except a one-way withdrawal timestamp; migration 0006 additionally protects disclosure snapshots. Legacy receipts lacking disclosure snapshots are shown as requiring onboarding review and are not retroactively treated as new acknowledgements.

API timestamps use naive UTC internally, as in the existing database; browser pages explicitly render them as UTC-derived local times. Policy wording changes require a new POLICY_VERSION and review. Configuration limits have a separately incremented retention-policy version. Consent receipt history is owner-only and auditable.

## State and routes

`GET /api/v1/me/onboarding` returns current disclosures, retention policy, latest receipt and whether current onboarding information has been acknowledged. A receipt with all choices false can complete acknowledgement; completing onboarding never means “all processing permitted.” A withdrawn receipt is incomplete for renewed processing until the student saves new choices.

`PUT /api/v1/students/{id}/consent` saves choices after server-side ownership/permission checks. `GET .../consent` returns the latest receipt; `GET .../consent/history` returns bounded receipt history. `DELETE .../consent` timestamps withdrawal, cancels pending/running jobs, revokes future research membership and expires raw media references. Repeating withdrawal succeeds without rewriting the original withdrawal timestamp. It does not deactivate the account or submit an erasure request.

The browser gateway derives student IDs from backend `/me`; it does not accept a client-selected owner. HttpOnly cookies and Origin checks remain the authentication boundary. Ownership is independently enforced again in FastAPI. `GET .../privacy`, `GET .../records?category=...` and POST/GET `.../data-controls` remain usable with no analysis permission. Human-support requests also remain available, though counselor access still requires reviewer consent and assignment.

## Queueing and executing work

`create_inference` locks the student, selects current unwithdrawn consent, validates account/session ownership and the model modality, and persists the chosen `input_modalities`. For a single-modality model its input must match exactly. A fusion run defaults to only currently permitted modalities; explicit input lists containing disabled, unknown or duplicate modalities are rejected. Optional absence is legitimate. No placeholder audio/video is synthesized to fill a missing input.

`run_analysis` is the supported worker entry point. It checks the latest receipt, exact queued receipt identity, immutable input manifest, parent record availability and exact payload-reference keys before invoking an adapter. Extra audio/visual references in a text-only job are rejected. Adapters receive only the permitted references. The worker saves running status and releases the consent lock before external execution, so withdrawal can take effect during long-running work. It then acquires current consent again and checks job status before publishing. A changed/withdrawn receipt or cancelled job discards the result. Adapter exceptions produce sanitized failure metadata, not payloads in logs.

Changing any consent choice cancels older pending/running jobs, even if a particular modality stayed enabled. A replacement job must be queued against the new receipt. Migration 0006 cancels legacy queued/running work so it can be requeued with an explicit manifest. Legacy completed evidence remains intact. Consent cannot undo computation that already occurred; the promise is to block new work and suppress revoked outputs.

`create_trend` and `register_research_use` use `require_purpose` for separate longitudinal/research permission. Research registration additionally requires a completed student-owned inference, ethics-approval reference and de-identification provenance. MySQL independently guards current modality/research/trend permissions and evidence lineage on writes. Application services supply the same consent boundary for ordinary worker use and SQLite tests. All future model workers must use these services; direct model calls or raw ORM writes are not an authorized application integration.

Worker payload references are trusted, owner-validated references supplied by a future storage/job layer, not arbitrary browser input. No real AI models are downloaded or invoked by onboarding. `ProcessingInput` is the worker contract; the earlier `ai/contracts.py` remains a model-adapter outline and must not become a bypass around this boundary.

## Retention and withdrawal boundaries

Recorded consent snapshots support shorter-of-disclosed/current retention deadlines. Raw media expiry is capped and cannot be extended by runtime writes. Revocation expires references but never sets `purged_at` without verified object erasure. Research memberships are revoked for future use; external exports/publications require independent recall/governance procedures. Institutional holds only affect retention, not processing permission. See [PRIVACY.md](PRIVACY.md) for defaults, request review and fulfillment limitations.

## Tests

`test_consent.py` runs on SQLite and optional isolated MySQL. Tests prove disabled text/audio/visual cannot be enqueued or reach the adapter; disabled payloads cannot enter text-only fusion; enabled text does execute; and withdrawal during execution prevents output persistence. Additional tests cover false optional defaults, independent tracking/research gates, version conflict detection, saved disclosure/timestamp evidence, idempotent withdrawal, privacy/support availability after declining, cross-user/role denial, raw-retention limits/expiry, and finite student-visible retention holds.

The MySQL suite also tests immutable receipts, current consent at publication, evidence lineage and research/longitudinal write guards. The production browser gateway test verifies Origin rejection and derives the student owner server-side. These tests do not claim real audio/visual model accuracy, physical object deletion, or live emergency monitoring.

Example text-only choice (read the actual versions from `/me/onboarding`):

```json
{
  "policy_version": "2026-10-03.2",
  "retention_version": 1,
  "expected_version": 0,
  "acknowledged": true,
  "text_processing": true,
  "audio_processing": false,
  "visual_processing": false,
  "longitudinal_tracking": false,
  "research_data_use": false,
  "reviewer_access": false,
  "retain_audio": false,
  "retain_visual": false
}
```
