# Privacy and student data controls

PamatiAI is a student-support research prototype. AI outputs are uncertain estimates, not diagnoses or clinical assessments. The student onboarding screen at `/student/onboarding` explains the purpose, automated analysis, limitations, human oversight, available/planned modalities, retention, research use, withdrawal and emergency limitations. The platform does not guarantee detection of distress, continuous monitoring or emergency dispatch.

## Choices and access

Text, audio, visual, longitudinal tracking and research permission are separate. Assigned-counselor access is an additional separate choice. New optional choices are unchecked. The student can acknowledge the information and decline every analysis choice, with the same access to privacy controls and support requests. Audio/visual consent does not activate device capture or authorize raw recording retention. This release has no microphone/camera capture. Conversational text uses the disclosed local baseline or explicitly configured model adapter; sentiment analysis remains a separate consent-enforcing adapter workflow.

Text permission is needed to create a conversational AI session. Previously available personal records remain readable after withdrawal. STUDENT routes check ownership server-side; counselors cannot use the student privacy inventory/export-request routes. Counselor access to support records requires current assignment and reviewer-access consent. Administrators manage accounts, retention configuration and request metadata without receiving automatic content access.

## What students can view and request

`/student/privacy` shows category counts, available record metadata, configured retention periods, active institutional holds, and export/deletion request status. `/student/records` reads available conversation messages and consent receipt history. A separate personal-export request can cover records requiring reviewed disclosure, including internal safety/review material; such material is not automatically placed in a general dashboard.

The inventory includes conversations, analysis runs, trend records, media references, research dataset membership and consent receipts. Record lists are bounded/paginated and include recorded timestamps and retention deadlines. Hidden conversations are identified as hidden in the inventory; logical hiding is not described as physical erasure. Media storage locations, credentials, tokens and internal risk narratives are never included in student inventory responses.

Students can request a personal export or deletion from the same authenticated account, including after declining or withdrawing analysis. Requests receive an ID, recorded timestamp and review target. They are durable requests for fulfillment, not immediate downloadable exports or claims that data was already deleted. The API cannot mark a request fulfilled based on an administrator assertion alone. Fulfillment must verify output ownership/redactions or deletion across primary storage, derived data, object storage, replicas and backups before reporting completion.

## Configurable retention

The `data_retention` system setting is validated server-side and editable only by ADMIN with configuration permission. These defaults are example configured limits, not a statement of a legally required period:

| Category | Default limit |
| --- | --- |
| Conversations | 180 days from creation |
| Analysis records | 90 days from creation |
| Research membership records | 365 days from creation |
| Consent/audit evidence | 1,825 days from creation |
| Explicitly permitted raw media | Maximum 24 hours; configuration bounded to 1–168 hours |
| Backup expiry window | 90 days; configuration bounded to 1–365 days |
| Privacy-request review target | 30 days; configuration bounded to 1–90 days |

The API versions configuration changes. Consent receipts preserve the policy displayed; new conversations preserve their retention policy. Linked analysis/research records derive their disclosed limits from their consent receipt. Calculated ordinary deadlines use the shorter of captured and current limits: changing configuration cannot silently extend a previously disclosed shorter period. Legacy records without snapshots use current policy and must be reviewed during institutional migration.

Raw retention additionally needs the environment opt-in, database raw-retention gate, analysis permission and explicit raw-retention permission. The onboarding flow never grants raw-retention permission. Creation rejects a raw expiry exceeding the current cap, and withdrawal/removing modality or raw-retention permission shortens existing media expiry. Expiry marks the object for erasure; it does not falsely mark an object purged. Raw-media storage and verified physical erasure workers remain deployment integrations. Run `python -m app.retention_report` to obtain aggregate due/held counts without printing content; it is a review report, not a deletion command.

## Legitimate restrictions and institutional review

A retention requirement must be recorded as a finite category-specific hold, with an institutional/legal basis, a student-visible explanation, an expiry and an administrator actor. This mechanism records a decision; it does not establish that the stated basis is legally valid. The institution must substantiate necessity, proportionality and the actual legal/research obligation. Research participation consent alone is not a blanket reason to retain everything indefinitely.

Administrators can list request metadata through `/api/v1/admin/data-controls` and review individual requests without reading conversation content. Only erasure requests can be deferred for a hold. The API requires a current documented hold before accepting deferral and sets a renewed review date. Students see the reason and expiry. Holds can be released and expire automatically in deadline calculations. A hold preserves relevant records; it does not reactivate AI, tracking, research or counselor access, authorize raw capture, or override current consent. Category holds do not imply that unrelated categories should be retained. ADMIN can review request metadata but must use separately authorized fulfillment workers for content exports.

Consent/audit evidence is append-only under runtime database privileges. Any final minimization/purge of that evidence requires a controlled, separately authorized maintenance process, compatible with validated institutional obligations. Backup deletion must follow the configured expiry window, and restored backups must reapply deletion/withdrawal decisions before data becomes available. The implementation calculates deadlines and records requests/holds; it does not claim to have physically erased every database or backup category.

## Withdrawal and research

Changing a choice appends a versioned receipt. Withdrawing all choices timestamps the latest receipt and is idempotent. Pending/running jobs are cancelled. Adapters cannot start on disabled inputs; a saved input manifest prevents optional data from being included in text-only fusion. Consent is checked again before saving a result, so a change during external execution discards that result. Work already performed cannot be undone.

Turning off research permission or withdrawing marks linked research memberships revoked for new use. Previously exported datasets, irreversible anonymization and published aggregate results require research governance review; revocation in this database cannot recall external copies automatically. Research workflows must independently verify ethics approval, purpose and de-identification provenance. No consent choice authorizes sale, advertising, facial identification or psychiatric inference.

## Deployment responsibilities

Before participant onboarding, the institution must approve actual retention periods, provide an accessible privacy/DPO contact and emergency-support information, define review staffing and request handling, validate appropriate export and erasure workers, and document approved research purposes. No real model adapters, storage-purge worker or external dataset recall are claimed as deployed in this change. Protect deployment with HTTPS, restricted credentials, encryption, audit monitoring and the existing authentication controls.

The design is informed by the Philippine National Privacy Commission's [Data Privacy Act implementing rules](https://privacy.gov.ph/implementing-rules-regulations-data-privacy-act-2012/) on transparency, legitimate purpose, proportionality and retention, and its [consent guidance compendium](https://privacy.gov.ph/wp-content/uploads/2024/05/2023-compendium-2.pdf) on accessible withdrawal. These references guide the design; institution-specific obligations still require an approved policy. Human-oversight and uncertainty disclosures follow the [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework).

## Conversational processing

Student chat uses text consent independently of audio, visual, longitudinal and research choices. The default provider runs predefined responses locally. A configured model endpoint receives only the system prompt and up to 20 recent text messages from that conversation. Provider/host/model/version are disclosed and saved in consent evidence; changing the processor requires renewed acknowledgment. Consent changes during generation discard the reply before publication but cannot retract processing already performed. Hiding history does not erase retained records. See [CONVERSATION.md](CONVERSATION.md).

## Direct personal download

The authenticated student can download available own records from `/student/privacy`, including after withdrawing consent. `/api/v1/students/{student_id}/data-download` independently checks ownership and excludes other identities, hidden/expired/deleted source content, raw media, credentials and privileged case notes. It returns a private JSON attachment, records only access metadata and enforces persistent rate limits. Limits are 10,000 rows per bounded collection, 10,000 messages total and 8 MB serialized output; oversized downloads return an explicit error and direct the student to an institutional request. The download contains sensitive personal data and must be stored privately. It neither reactivates processing nor fulfills broader institutional disclosure/erasure requests.
