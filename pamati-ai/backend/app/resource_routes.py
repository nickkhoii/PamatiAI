"""Resource routes enforce permissions and ownership before reading sensitive rows."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, StrictBool
from sqlalchemy import func, select

from app.auth_dependencies import DB, CurrentUser, audit, authorize_student, require_permission
from app.auth_routes import AccountManager, Admin, Input
from app.consent_policy import POLICY_VERSION, policy_document
from app.models import (
    ConsentRecord,
    Conversation,
    DataControlRequest,
    HumanReview,
    InteractionSession,
    Message,
    ReferralRecord,
    ReviewerAssignment,
    ReviewerProfile,
    RiskSignal,
    SentimentObservation,
    SentimentTrend,
    StudentProfile,
    SupportRequest,
    SystemSetting,
    TrendObservation,
    User,
    utcnow,
)
from app.persistence import ConsentDenied, current_consent, record_consent, withdraw_consent
from app.retention import RetentionPolicy, retention_policy

router = APIRouter(prefix="/api/v1", tags=["protected resources"])
ConfigurationManager = Annotated[User, Depends(require_permission("configuration:manage"))]


class ConsentInput(Input):
    policy_version: str = Field(min_length=1, max_length=80)
    acknowledged: StrictBool = False
    expected_version: int | None = Field(default=None, ge=0)
    retention_version: int | None = Field(default=None, ge=1)
    text_processing: StrictBool = False
    audio_processing: StrictBool = False
    visual_processing: StrictBool = False
    longitudinal_tracking: StrictBool = False
    research_data_use: StrictBool = False
    reviewer_access: StrictBool = False
    retain_audio: StrictBool = False
    retain_visual: StrictBool = False


class DataInput(Input):
    kind: Literal["export", "erasure"]


class ReviewInput(Input):
    decision: Literal["acknowledge", "dismiss", "follow_up", "refer"]
    notes: str | None = Field(default=None, max_length=10000)


class ReferralInput(Input):
    human_review_id: str = Field(max_length=36)
    service_reference: str = Field(min_length=1, max_length=255)


class ReferralState(Input):
    status: Literal["offered", "accepted", "declined", "closed"]


class AssignmentInput(Input):
    student_id: str = Field(max_length=36)
    counselor_id: str = Field(max_length=36)
    revoked: bool = False


class SettingInput(Input):
    value: dict


def receipt_view(c):
    if c is None:
        return None
    return {
        "id": c.id,
        "version": c.version,
        "created_at": c.created_at,
        "withdrawn_at": c.withdrawn_at,
        "disclosure_snapshot": c.disclosure_snapshot,
        **{
            name: getattr(c, name)
            for name in ConsentInput.model_fields
            if name not in {"acknowledged", "expected_version", "retention_version"}
        },
    }


@router.get("/students/{student_id}/conversations")
def conversations(student_id: str, db: DB, user: CurrentUser):
    authorize_student(db, user, "history:read", student_id)
    rows = db.scalars(
        select(Conversation)
        .where(Conversation.student_id == student_id, Conversation.deleted_at.is_(None))
        .order_by(Conversation.created_at.desc())
        .limit(100)
    )
    result = [{"id": c.id, "status": c.status, "created_at": c.created_at} for c in rows]
    audit(db, user.id, "conversation.list", "student", student_id)
    db.commit()
    return result


@router.post("/students/{student_id}/conversations", status_code=201)
def create_conversation(student_id: str, db: DB, user: CurrentUser):
    authorize_student(db, user, "conversation:manage", student_id)
    try:
        receipt = current_consent(db, student_id)
        if not receipt.text_processing:
            raise ConsentDenied("Text analysis consent is required for conversational AI")
    except ConsentDenied as exc:
        raise HTTPException(409, str(exc)) from None
    row = Conversation(student_id=student_id, retention_snapshot=retention_policy(db).model_dump())
    db.add(row)
    db.flush()
    audit(db, user.id, "conversation.created", "conversation", row.id)
    db.commit()
    return {"id": row.id, "status": row.status}


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: str, db: DB, user: CurrentUser,
                 offset: int = Query(default=0, ge=0, le=100000), limit: int = Query(default=100, ge=1, le=500)):
    row = db.get(Conversation, conversation_id)
    if not row or row.deleted_at:
        raise HTTPException(404, "Conversation not found")
    authorize_student(db, user, "history:read", row.student_id)
    messages = list(db.scalars(
        select(Message)
        .join(InteractionSession, Message.session_id == InteractionSession.id)
        .where(
            InteractionSession.conversation_id == row.id,
            InteractionSession.deleted_at.is_(None),
            Message.student_id == row.student_id,
            Message.deleted_at.is_(None),
        )
        .order_by(InteractionSession.created_at.desc(), InteractionSession.id.desc(), Message.sequence_number.desc())
        .offset(offset)
        .limit(limit + 1)
    ))
    result = {
        "id": row.id,
        "status": row.status,
        "messages": [{"id": m.id, "session_id": m.session_id, "sender": m.sender, "text": m.text_content,
                      "created_at": m.created_at, "generation": m.generation} for m in reversed(messages[:limit])],
        "next_offset": offset + limit if len(messages) > limit else None,
    }
    audit(db, user.id, "conversation.read", "conversation", row.id)
    db.commit()
    return result


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, db: DB, user: CurrentUser):
    row = db.get(Conversation, conversation_id)
    if not row or row.deleted_at:
        raise HTTPException(404, "Conversation not found")
    authorize_student(db, user, "conversation:manage", row.student_id)
    row.deleted_at = utcnow()
    audit(db, user.id, "conversation.hidden", "conversation", row.id)
    db.commit()


@router.get("/students/{student_id}/consent")
def consent(student_id: str, db: DB, user: CurrentUser):
    authorize_student(db, user, "consent:manage", student_id)
    row = db.scalar(
        select(ConsentRecord)
        .where(ConsentRecord.student_id == student_id)
        .order_by(ConsentRecord.version.desc())
        .limit(1)
    )
    return receipt_view(row)


@router.put("/students/{student_id}/consent")
def manage_consent(student_id: str, body: ConsentInput, db: DB, user: CurrentUser):
    authorize_student(db, user, "consent:manage", student_id)
    if body.policy_version != POLICY_VERSION or not body.acknowledged:
        raise HTTPException(409, "Review and acknowledge the current consent information")
    try:
        from app.persistence import lock_student

        lock_student(db, student_id)
        previous = db.scalar(
            select(ConsentRecord)
            .where(ConsentRecord.student_id == student_id)
            .order_by(ConsentRecord.version.desc())
            .limit(1)
            .with_for_update()
        )
        if body.expected_version is not None and body.expected_version != (
            previous.version if previous else 0
        ):
            raise HTTPException(409, "Consent changed. Reload your choices before saving.")
        snapshot = policy_document()
        policy = retention_policy(db, lock=True)
        if body.retention_version != policy.version:
            raise HTTPException(
                409, "Retention information changed. Reload and review it before saving."
            )
        snapshot["retention"] = policy.model_dump()
        row = record_consent(
            db,
            student_id,
            disclosure_snapshot=snapshot,
            **body.model_dump(exclude={"acknowledged", "expected_version", "retention_version"}),
        )
    except ConsentDenied as exc:
        raise HTTPException(409, str(exc)) from None
    audit(db, user.id, "consent.updated", "consent", row.id)
    db.commit()
    return receipt_view(row)


@router.delete("/students/{student_id}/consent", status_code=204)
def revoke_consent(student_id: str, db: DB, user: CurrentUser):
    authorize_student(db, user, "consent:manage", student_id)
    try:
        withdraw_consent(db, student_id)
    except ConsentDenied:
        raise HTTPException(409, "No active consent") from None
    audit(db, user.id, "consent.withdrawn", "student", student_id)
    db.commit()


@router.get("/students/{student_id}/trends")
def trends(student_id: str, db: DB, user: CurrentUser):
    authorize_student(db, user, "history:read", student_id)
    consent = db.scalar(
        select(ConsentRecord)
        .where(ConsentRecord.student_id == student_id)
        .order_by(ConsentRecord.version.desc())
        .limit(1)
    )
    if not consent or consent.withdrawn_at or not consent.longitudinal_tracking:
        return []
    rows = db.scalars(
        select(SentimentTrend)
        .where(SentimentTrend.student_id == student_id, SentimentTrend.deleted_at.is_(None))
        .order_by(SentimentTrend.window_end.desc())
        .limit(100)
    )
    # Student summaries deliberately exclude model labels, internal explanations and risk narratives.
    result = [
        {
            "id": t.id,
            "dimension": t.dimension,
            "window_start": t.window_start,
            "window_end": t.window_end,
            "sample_count": t.sample_count,
            "average_score": db.scalar(
                select(func.avg(SentimentObservation.score))
                .join(TrendObservation, TrendObservation.observation_id == SentimentObservation.id)
                .where(
                    TrendObservation.trend_id == t.id,
                    SentimentObservation.student_id == student_id,
                    SentimentObservation.deleted_at.is_(None),
                )
            ),
        }
        for t in rows
    ]
    audit(db, user.id, "trend.read", "student", student_id)
    db.commit()
    return result


@router.post("/students/{student_id}/support-requests", status_code=201)
def support(student_id: str, db: DB, user: CurrentUser):
    authorize_student(db, user, "support:request", student_id)
    row = SupportRequest(student_id=student_id)
    db.add(row)
    db.flush()
    audit(db, user.id, "support.requested", "support_request", row.id)
    db.commit()
    return {"id": row.id, "status": row.status}


@router.get("/students/{student_id}/support-requests")
def support_requests(student_id: str, db: DB, user: CurrentUser):
    permission = "support:request" if student_id == user.id else "review:manage"
    authorize_student(db, user, permission, student_id)
    return [
        {"id": r.id, "status": r.status}
        for r in db.scalars(
            select(SupportRequest).where(SupportRequest.student_id == student_id).limit(100)
        )
    ]


@router.post("/students/{student_id}/data-controls", status_code=202)
def data_controls(student_id: str, body: DataInput, db: DB, user: CurrentUser):
    authorize_student(db, user, "privacy:manage", student_id)
    row = DataControlRequest(student_id=student_id, kind=body.kind)
    from datetime import timedelta

    row.review_due_at = utcnow() + timedelta(days=retention_policy(db).request_review_days)
    db.add(row)
    db.flush()
    audit(db, user.id, "privacy.requested", "data_control", row.id)
    db.commit()
    return {
        "id": row.id,
        "kind": row.kind,
        "status": row.status,
        "review_due_at": row.review_due_at,
    }


@router.get("/students/{student_id}/data-controls")
def data_requests(student_id: str, db: DB, user: CurrentUser):
    authorize_student(db, user, "privacy:manage", student_id)
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "status": r.status,
            "created_at": r.created_at,
            "review_due_at": r.review_due_at,
            "decision_reason": r.decision_reason,
        }
        for r in db.scalars(
            select(DataControlRequest).where(DataControlRequest.student_id == student_id).limit(100)
        )
    ]


@router.get("/students/{student_id}/safety-signals")
def signals(student_id: str, db: DB, user: CurrentUser):
    authorize_student(db, user, "review:manage", student_id)
    rows = db.scalars(
        select(RiskSignal)
        .where(RiskSignal.student_id == student_id, RiskSignal.deleted_at.is_(None))
        .limit(100)
    )
    result = [
        {"id": r.id, "priority": r.priority, "status": r.status, "explanation": r.explanation}
        for r in rows
    ]
    audit(db, user.id, "safety.read", "student", student_id)
    db.commit()
    return result


@router.post("/safety-signals/{signal_id}/reviews", status_code=201)
def review(signal_id: str, body: ReviewInput, db: DB, user: CurrentUser):
    signal = db.get(RiskSignal, signal_id)
    if not signal or signal.deleted_at:
        raise HTTPException(404, "Signal not found")
    authorize_student(db, user, "review:manage", signal.student_id)
    row = HumanReview(
        student_id=signal.student_id,
        risk_signal_id=signal.id,
        reviewer_id=user.id,
        **body.model_dump(),
    )
    db.add(row)
    db.flush()
    audit(db, user.id, "review.created", "human_review", row.id)
    db.commit()
    return {"id": row.id}


@router.get("/students/{student_id}/reviews")
def reviews(student_id: str, db: DB, user: CurrentUser):
    authorize_student(db, user, "review:manage", student_id)
    result = [
        {"id": r.id, "decision": r.decision, "notes": r.notes}
        for r in db.scalars(
            select(HumanReview).where(HumanReview.student_id == student_id).limit(100)
        )
    ]
    audit(db, user.id, "review.read", "student", student_id)
    db.commit()
    return result


@router.post("/students/{student_id}/referrals", status_code=201)
def referral(student_id: str, body: ReferralInput, db: DB, user: CurrentUser):
    authorize_student(db, user, "review:manage", student_id)
    review = db.get(HumanReview, body.human_review_id)
    if not review or review.student_id != student_id:
        raise HTTPException(404, "Review not found")
    row = ReferralRecord(student_id=student_id, **body.model_dump())
    db.add(row)
    db.flush()
    audit(db, user.id, "referral.created", "referral", row.id)
    db.commit()
    return {"id": row.id, "status": row.status}


@router.get("/students/{student_id}/referrals")
def referrals(student_id: str, db: DB, user: CurrentUser):
    authorize_student(db, user, "review:manage", student_id)
    result = [
        {"id": r.id, "status": r.status, "service_reference": r.service_reference}
        for r in db.scalars(
            select(ReferralRecord)
            .where(ReferralRecord.student_id == student_id, ReferralRecord.deleted_at.is_(None))
            .limit(100)
        )
    ]
    audit(db, user.id, "referral.read", "student", student_id)
    db.commit()
    return result


@router.patch("/referrals/{referral_id}")
def referral_status(referral_id: str, body: ReferralState, db: DB, user: CurrentUser):
    row = db.get(ReferralRecord, referral_id)
    if not row or row.deleted_at:
        raise HTTPException(404, "Referral not found")
    authorize_student(db, user, "review:manage", row.student_id)
    row.status = body.status
    audit(db, user.id, "referral.updated", "referral", row.id)
    db.commit()
    return {"id": row.id, "status": row.status}


@router.put("/admin/assignments")
def assignment(body: AssignmentInput, db: DB, admin: Admin, manager: AccountManager):
    student = db.get(StudentProfile, body.student_id)
    reviewer = db.get(ReviewerProfile, body.counselor_id)
    if (
        not student
        or student.deleted_at
        or not reviewer
        or reviewer.deleted_at
        or not student.user.is_active
        or not reviewer.user.is_active
        or "COUNSELOR" not in {r.code for r in reviewer.user.roles}
    ):
        raise HTTPException(404, "Active student and counselor required")
    row = db.scalar(
        select(ReviewerAssignment)
        .where(
            ReviewerAssignment.student_id == body.student_id,
            ReviewerAssignment.reviewer_id == body.counselor_id,
        )
        .with_for_update()
    )
    if not row:
        row = ReviewerAssignment(
            student_id=body.student_id, reviewer_id=body.counselor_id, assigned_by=admin.id
        )
        db.add(row)
    row.revoked_at = utcnow() if body.revoked else None
    db.flush()
    audit(
        db,
        admin.id,
        "assignment.revoked" if body.revoked else "assignment.granted",
        "assignment",
        row.id,
    )
    db.commit()
    return {"id": row.id, "revoked": body.revoked}


@router.get("/admin/settings")
def settings(db: DB, admin: Admin, manager: ConfigurationManager):
    return [{"key": r.key, "value": r.value} for r in db.scalars(select(SystemSetting))]


@router.put("/admin/settings/{key}")
def update_setting(
    key: str, body: SettingInput, db: DB, admin: Admin, manager: ConfigurationManager
):
    # Only existing non-secret configuration can be changed through the API.
    row = db.get(SystemSetting, key, with_for_update=True, populate_existing=True)
    if not row:
        raise HTTPException(404, "Setting not found")
    if key == "data_retention":
        from pydantic import ValidationError

        try:
            candidate = RetentionPolicy.model_validate(body.value)
        except ValidationError:
            raise HTTPException(422, "Invalid retention limits") from None
        candidate.version = retention_policy(db).version + 1
        row.value = candidate.model_dump()
    elif (
        key == "raw_media_retention"
        and set(body.value) == {"enabled"}
        and type(body.value["enabled"]) is bool
    ):
        row.value = body.value
    else:
        raise HTTPException(422, "Unsupported configuration value")
    row.updated_by = admin.id
    audit(db, admin.id, "configuration.updated", "setting")
    db.commit()
    return {"key": key, "value": row.value}
