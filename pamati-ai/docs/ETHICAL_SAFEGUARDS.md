# Ethical safeguards

Reviewed 2026-10-09 alongside [SECURITY_AUDIT.md](SECURITY_AUDIT.md). PamatiAI is a student-support research system. Sentiment, modeled affect, vocal features and observed expression are limited computational observations, not diagnoses, reliable measurements of internal mental state, or proof of risk.

## Agency and informed consent

Students receive versioned disclosures of processing purposes, optional modalities, model/provider details, retention and human access. Optional permissions default off and require explicit booleans. Text, audio, visual, longitudinal tracking, research participation, reviewer access and optional raw-media retention are separate choices. Declining optional processing does not remove privacy controls, human-support requests or resources.

The system records immutable, timestamped receipts and disclosure snapshots. Changes in relevant processing/disclosure configuration require renewed review. Withdrawal and replacement receipts invalidate processing permissions; workers check before execution and before publication. Withdrawal can discard work already in progress, but cannot retract data already transmitted to an approved external processor or stop every in-flight computation instantly. Provider agreements and deletion procedures must address that boundary.

There is no implicit audio/video collection, automatic device activation or background surveillance. Optional uploads require explicit current permission, an active owned session, and server-side modality authorization. Browser device permissions remain blocked. Visual expression cannot establish emotion, identity, ethnicity, personality, deception or a psychiatric condition.

## Human oversight and respectful presentation

The student dashboard uses understandable check-ins and personal trends without a universal mental-health score, diagnostic label or frightening risk ranking. Missing data and abstention remain visible as missing information. Students may request trained human support and consult institution-approved resources.

Counselor views distinguish **AI-generated observation** from **human-reviewed assessment**. A human review is still a documented contextual judgment, not automatically a clinical diagnosis or evaluation gold label. Review access requires current assignment and student reviewer-access consent. Workflow revisions, notes, referrals and student acceptance/refusal are auditable. Removal of a counselor role revokes assignments rather than silently restoring them later.

Administrators manage users, roles, configuration, retention, resources and audit metadata. Those responsibilities do not justify reading student conversations or case notes. Research users do not inherit identifiable-content access from a role name. No model can grant permissions, change consent, contact another person, make a disciplinary decision or dispatch emergency services.

The system is not continuously monitored and a support request is not an emergency service. Institutions must approve staffing, response expectations, escalation criteria, appeals, safeguarding obligations and verified local contacts before participant use. Do not fabricate a resource directory or imply a referral was acted on merely because a database row exists.

## Privacy and retention

Application/audit logging excludes conversation content, case notes, credentials and recovery tokens. A generic error and generated request ID support troubleshooting without exposing submitted values. Default access logging is disabled; ingress, provider, database, backup and APM behavior must receive independent operational review.

Source deletion or expiry prevents ordinary reuse in processing, trends, review evidence and research export. Stored retention snapshots prevent an ordinary policy increase from silently extending an earlier shorter disclosure. Finite, documented holds do not create new processing or content-access rights. Owners can inspect limited privacy metadata, including applicable deadlines, without being shown a false claim that storage has been erased.

Raw audio is exceptional: environment approval, institutional configuration and separate student permission must all allow retention. Temporary files are private and removed after work. Visual raw retention is unavailable. Physical erasure across databases, object stores, exports, replicas and backups requires verified operational workflows; soft deletion and an accepted erasure request are not proof of completion.

## Research integrity

Research export requires current research-purpose consent, explicitly approved dataset membership, ethics/deidentification provenance and consent that covered the original source. Later permission cannot relabel historical unconsented evidence. Exports omit raw conversations/media, names, emails, case notes, internal record IDs and student timestamps, use dataset-specific keyed pseudonyms, and suppress participant groups smaller than five. Reidentification/linkage remain possible; keys and exports require separate access restrictions, approval and retention.

AI observations are never labeled ground truth. Independent annotation, appropriate datasets, held-out participant splits, model/dataset versions and reproducible parameters are necessary for doctoral evidence. Synthetic fixtures test software behavior only. Without a real labeled dataset, report exactly **"Not evaluated — labeled dataset required."** Do not reinterpret tests or an unlabeled export as model accuracy, clinical validity or safety validation.

The evaluation framework supports applicable classification/calibration metrics and modality comparisons, but scientific claims must distinguish dataset validity, availability/abstention, target semantics and independent labels. Use the [evaluation guide](EVALUATION.md) and [research protocol](RESEARCH_PROTOCOL.md), and obtain independent institutional ethics approval before collection or export.

## Institutional responsibilities and residual risks

Bias, cultural/language differences, disability, missing modalities and environmental conditions can change model behavior. Literal safety rules can miss context or overreact to quoted, negated or figurative language. Output phrase filters do not prove a learned model is safe. Evaluate false alarms, missed signals, reviewer disagreement, calibration, accessibility, distress and possible coercion with participants and qualified reviewers.

No local check establishes clinical utility, legal compliance, institutional staffing, actual emergency-response capacity or the effectiveness of a deployed model. Staff MFA/SSO, full browser/assistive-technology testing, external processor auditing, completed erasure procedures and operational security review remain necessary. Keep participation voluntary, provide an alternative route to support, forbid punitive use, and offer a documented way to challenge an AI observation or human review.
