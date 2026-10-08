"""Consent-aware safety observations and auditable, human-only workflow transitions."""
from fastapi import HTTPException
from sqlalchemy import select

from app import config
from app.auth_dependencies import audit, authorize_student
from app.models import (
    Conversation,
    HumanReview,
    InteractionSession,
    Message,
    ModelInference,
    ReferralRecord,
    ReviewerAssignment,
    RiskSignal,
    SentimentTrend,
)
from app.persistence import ConsentDenied, current_consent
from services.safety.policy import LiteralSafetyAnalyzer, SafetyPolicy, evaluate
from services.safety.resources import SafetyResource


def configured():
    settings = config.get_settings()
    policy = SafetyPolicy(**settings.safety_policy)
    if len(settings.safety_resources) > 16:
        raise ValueError("Configure at most sixteen verified safety resources")
    resources = tuple(SafetyResource(**r) for r in settings.safety_resources)
    if len({r.id for r in resources}) != len(resources):
        raise ValueError("Safety resource IDs must be unique")
    return policy, resources


def disclosure():
    policy, _resources = configured()
    return {"processor": "PamatiAI server", "analyzer": LiteralSafetyAnalyzer.version,
            "policy_version": policy.version, "policy_sha256": policy.fingerprint,
            "policy": policy.model_dump(),
            "diagnosis": "not_supported", "automatic_dispatch": False}


def screen(text):
    policy, resources = configured()
    observations = LiteralSafetyAnalyzer().analyze(text, policy)
    return evaluate(observations, policy), policy, resources


def record_signals(db, message, candidates, policy, receipt):
    latest = current_consent(db, message.student_id)
    if latest.id != receipt.id or not latest.text_processing or message.deleted_at:
        raise ConsentDenied("Safety processing authorization changed")
    if (latest.disclosure_snapshot or {}).get("safety_processing", {}).get("policy_sha256") != policy.fingerprint:
        raise ConsentDenied("Safety rules changed; review the current disclosure")
    result = []
    for candidate in sorted(candidates, key=lambda c: (c.priority != "urgent", c.rule_id)):
        signal = RiskSignal(student_id=message.student_id, source_message_id=message.id,
                            consent_record_id=receipt.id, signal_code=candidate.reason_category,
                            priority=candidate.priority, rule_version=policy.fingerprint, confidence=None,
                            explanation={"schema_version": "safety-observation-v1", "reason_category": candidate.reason_category,
                                         "rule_id": candidate.rule_id, "rule_version": policy.version,
                                         "analyzer_version": LiteralSafetyAnalyzer.version,
                                         "policy_sha256": policy.fingerprint, "policy_snapshot": policy.model_dump(),
                                         "confidence_method": candidate.confidence_method,
                                         "interpretation": "language_requires_contextual_human_review_not_diagnosis"})
        # Multiple literal rules may describe the same category; avoid duplicate workflow items.
        if any(s.signal_code == signal.signal_code for s in result):
            continue
        db.add(signal)
        db.flush()
        audit(db, None, "safety.signal_created", "risk_signal", signal.id)
        result.append(signal)
    return result


def source_live(db, signal):
    if signal.deleted_at:
        return False
    if signal.source_message_id:
        message = db.scalar(select(Message).where(Message.id == signal.source_message_id)
                            .with_for_update().execution_options(populate_existing=True))
        session = db.scalar(select(InteractionSession).where(InteractionSession.id == message.session_id)
                            .with_for_update().execution_options(populate_existing=True)) if message else None
        conversation = db.scalar(select(Conversation).where(Conversation.id == session.conversation_id)
                                 .with_for_update().execution_options(populate_existing=True)) if session else None
        return bool(message and not message.deleted_at and session and not session.deleted_at
                    and conversation and not conversation.deleted_at)
    if signal.inference_id:
        inference = db.get(ModelInference, signal.inference_id, populate_existing=True)
        if not inference or inference.deleted_at:
            return False
        if inference.message_id:
            message = db.get(Message, inference.message_id, populate_existing=True)
            if not message or message.deleted_at:
                return False
        session = db.get(InteractionSession, inference.session_id, populate_existing=True)
        return bool(session and not session.deleted_at and not session.conversation.deleted_at)
    trend = db.get(SentimentTrend, signal.trend_id, populate_existing=True)
    return bool(trend and not trend.deleted_at)


def authorized_signal(db, user, signal_id, *, lock=True):
    signal = db.get(RiskSignal, signal_id)
    if not signal:
        raise HTTPException(404, "Signal not found")
    # Lock the student/current receipt before evidence consistently with consent changes.
    try:
        receipt = current_consent(db, signal.student_id)
    except ConsentDenied:
        raise HTTPException(403, "Review access is unavailable") from None
    authorize_student(db, user, "review:manage", signal.student_id)
    assignment = db.scalar(select(ReviewerAssignment).where(
        ReviewerAssignment.student_id == signal.student_id, ReviewerAssignment.reviewer_id == user.id,
        ReviewerAssignment.revoked_at.is_(None)).with_for_update().execution_options(populate_existing=True))
    if not receipt.reviewer_access or not assignment:
        raise HTTPException(403, "Current reviewer permission and assignment are required")
    if lock:
        signal = db.scalar(select(RiskSignal).where(RiskSignal.id == signal_id)
                           .with_for_update().execution_options(populate_existing=True))
    if not source_live(db, signal):
        raise HTTPException(404, "Signal source is unavailable")
    return signal


def signal_view(signal):
    state = signal.workflow_state
    return {"id": signal.id, "student_id": signal.student_id, "priority": signal.priority,
            "status": signal.status, "workflow_state": state, "revision": signal.revision,
            "reason_category": signal.signal_code, "timestamp": signal.created_at,
            "source": {"message_id": signal.source_message_id, "inference_id": signal.inference_id, "trend_id": signal.trend_id},
            "rule_version": signal.rule_version, "confidence": signal.confidence,
            "assigned_reviewer_id": signal.assigned_reviewer_id,
            "human_review_status": "not_started" if state == "new" else "in_progress" if state == "under_review" else "completed",
            "explanation": signal.explanation}


def review_action(db, user, signal_id, *, decision, notes=None, expected_revision=None):
    signal = authorized_signal(db, user, signal_id)
    if expected_revision is not None and signal.revision != expected_revision:
        raise HTTPException(409, "The workflow changed; reload before acting")
    if signal.source_message_id and expected_revision is None:
        raise HTTPException(422, "A current workflow revision is required")
    if signal.source_message_id and (not notes or not notes.strip()):
        raise HTTPException(422, "Document the context and intended follow-up")
    if signal.assigned_reviewer_id and signal.assigned_reviewer_id != user.id:
        active = db.scalar(select(ReviewerAssignment.id).where(
            ReviewerAssignment.student_id == signal.student_id,
            ReviewerAssignment.reviewer_id == signal.assigned_reviewer_id,
            ReviewerAssignment.revoked_at.is_(None)).with_for_update())
        if active:
            raise HTTPException(409, "Another authorized reviewer is handling this item")
    previous = signal.workflow_state
    if decision == "reopen":
        if previous not in {"resolved", "referred"}:
            raise HTTPException(409, "Only completed workflow items can be reopened")
        state = "new"
    else:
        if previous in {"resolved", "referred"}:
            raise HTTPException(409, "Reopen the workflow item before recording another review")
        if decision in {"acknowledge", "follow_up", "refer"}:
            state = "under_review"  # A referral proposal is not yet a documented referral.
        elif decision in {"resolve", "dismiss"}:
            state = "resolved"
        else:
            raise HTTPException(422, "Unknown reviewer action")
    signal.workflow_state = state
    signal.status = {"new": "pending_review", "under_review": "acknowledged", "resolved": "resolved"}[state]
    if decision == "dismiss":
        signal.status = "dismissed"
    signal.assigned_reviewer_id = None if state == "new" else user.id
    signal.revision += 1
    row = HumanReview(student_id=signal.student_id, risk_signal_id=signal.id, reviewer_id=user.id,
                      decision=decision, notes=notes, workflow_from=previous, workflow_to=state,
                      signal_revision=signal.revision)
    db.add(row)
    db.flush()
    audit(db, user.id, "review." + decision, "human_review", row.id)
    return row, signal


def offer_referral(db, user, student_id, review_id, service_reference):
    review = db.get(HumanReview, review_id)
    if not review or review.student_id != student_id:
        raise HTTPException(404, "Review not found")
    signal = authorized_signal(db, user, review.risk_signal_id)
    if review.decision != "refer" or review.reviewer_id != user.id or signal.assigned_reviewer_id != user.id:
        raise HTTPException(409, "A documented referral decision by the handling reviewer is required")
    latest = db.scalar(select(HumanReview.id).where(HumanReview.risk_signal_id == signal.id)
                       .order_by(HumanReview.created_at.desc(), HumanReview.id.desc()).limit(1))
    if ((review.signal_revision is not None and review.signal_revision != signal.revision)
            or (review.signal_revision is None and latest != review.id)
            or signal.workflow_state != "under_review"):
        raise HTTPException(409, "The referral proposal is no longer current")
    if signal.source_message_id:
        _, resources = configured()
        if service_reference not in {r.id for r in resources}:
            raise HTTPException(422, "Choose an institution-configured referral resource")
    row = ReferralRecord(student_id=student_id, human_review_id=review.id, service_reference=service_reference)
    db.add(row)
    signal.workflow_state, signal.status = "referred", "acknowledged"
    signal.revision += 1
    db.flush()
    audit(db, user.id, "referral.offered", "referral", row.id)
    return row
