from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import func, select

from app.auth_dependencies import DB, CurrentUser, audit, authorize_student, require_permission
from app.auth_routes import Input
from app.models import (
    ConsentRecord,
    HumanReview,
    ReferralRecord,
    ReviewerAssignment,
    RiskSignal,
    utcnow,
)
from app.safety import authorized_signal, configured, signal_view, source_live

router = APIRouter(prefix="/api/v1", tags=["human safety review"])
Reviewer = Annotated[object, Depends(require_permission("review:manage"))]


@router.get("/safety/resources")
def resources():
    _, directory = configured()
    return {"resources": [r.model_dump() for r in directory], "automatic_dispatch": False,
            "message": "For immediate danger, contact appropriate local emergency services or a trusted person. Do not wait for this chat."}


@router.get("/reviewer/safety-queue")
def queue(db: DB, user: CurrentUser, reviewer: Reviewer,
          state: Literal["new", "under_review", "resolved", "referred"] = "new",
          offset: int = Query(default=0, ge=0, le=100000), limit: int = Query(default=30, ge=1, le=100)):
    latest = select(func.max(ConsentRecord.version)).where(ConsentRecord.student_id == RiskSignal.student_id).correlate(RiskSignal).scalar_subquery()
    rows = list(db.scalars(select(RiskSignal).join(ReviewerAssignment, ReviewerAssignment.student_id == RiskSignal.student_id)
                          .join(ConsentRecord, ConsentRecord.student_id == RiskSignal.student_id).where(
        ReviewerAssignment.reviewer_id == user.id, ReviewerAssignment.revoked_at.is_(None),
        ConsentRecord.version == latest, ConsentRecord.withdrawn_at.is_(None), ConsentRecord.reviewer_access.is_(True),
        RiskSignal.deleted_at.is_(None), RiskSignal.workflow_state == state,
    ).order_by((RiskSignal.priority == "urgent").desc(), (RiskSignal.priority == "prompt").desc(),
               RiskSignal.created_at, RiskSignal.id).offset(offset).limit(limit + 1)))
    items = []
    for row in rows[:limit]:
        try:
            signal = authorized_signal(db, user, row.id)
        except HTTPException as exc:
            if exc.status_code in {403, 404}:
                continue
            raise
        items.append(signal_view(signal))
    audit(db, user.id, "safety.queue_read", "reviewer", user.id)
    db.commit()
    return {"items": items, "next_offset": offset + limit if len(rows) > limit else None,
            "continuous_monitoring": False, "automatic_dispatch": False}


@router.get("/safety-signals/{signal_id}/workflow")
def detail(signal_id: str, db: DB, user: CurrentUser):
    signal = authorized_signal(db, user, signal_id)
    result = signal_view(signal)
    if signal.source_message_id:
        from app.models import Message
        message = db.get(Message, signal.source_message_id)
        result["source_message"] = {"id": message.id, "session_id": message.session_id,
                                    "text": message.text_content, "timestamp": message.created_at}
    result["actions"] = [{"id": r.id, "decision": r.decision, "notes": r.notes, "reviewer_id": r.reviewer_id,
                          "timestamp": r.created_at, "workflow_from": r.workflow_from, "workflow_to": r.workflow_to}
                         for r in db.scalars(select(HumanReview).where(HumanReview.risk_signal_id == signal.id)
                                             .order_by(HumanReview.created_at, HumanReview.id).limit(100))]
    result["referrals"] = [{"id": r.id, "service_reference": r.service_reference, "status": r.status,
                            "created_at": r.created_at, "student_decided_at": r.student_decided_at}
                           for r in db.scalars(select(ReferralRecord).join(HumanReview).where(
                               HumanReview.risk_signal_id == signal.id, ReferralRecord.deleted_at.is_(None)).limit(100))]
    audit(db, user.id, "safety.workflow_read", "risk_signal", signal.id)
    db.commit()
    return result


class StudentDecision(Input):
    status: Literal["accepted", "declined"]
    expected_status: Literal["offered", "accepted", "declined"] = Field(default="offered")


@router.get("/students/{student_id}/safety-follow-ups")
def followups(student_id: str, db: DB, user: CurrentUser):
    authorize_student(db, user, "history:read", student_id)
    _, directory = configured()
    labels = {r.id: r.label for r in directory}
    rows = db.scalars(select(ReferralRecord).where(ReferralRecord.student_id == student_id,
                                                  ReferralRecord.deleted_at.is_(None)).order_by(ReferralRecord.created_at.desc()).limit(100))
    result = []
    for row in rows:
        review = db.get(HumanReview, row.human_review_id)
        if not review or not source_live(db, review.risk_signal):
            continue
        result.append({"id": row.id, "service_reference": row.service_reference, "service_label": labels.get(row.service_reference, "Recorded support offer"),
                       "status": row.status, "created_at": row.created_at, "automatic_contact": False})
    audit(db, user.id, "safety.followups_read", "student", student_id)
    db.commit()
    return result


@router.patch("/students/{student_id}/safety-follow-ups/{referral_id}")
def decide(student_id: str, referral_id: str, body: StudentDecision, db: DB, user: CurrentUser):
    authorize_student(db, user, "support:request", student_id)
    if user.id != student_id:
        raise HTTPException(403, "The student records their own choice")
    row = db.scalar(select(ReferralRecord).where(ReferralRecord.id == referral_id).with_for_update().execution_options(populate_existing=True))
    if not row or row.student_id != student_id or row.deleted_at:
        raise HTTPException(404, "Follow-up offer not found")
    if row.status != body.expected_status or row.status == "closed":
        raise HTTPException(409, "This offer changed; reload before recording your choice")
    review = db.get(HumanReview, row.human_review_id)
    if not review or not source_live(db, review.risk_signal):
        raise HTTPException(404, "Follow-up source is unavailable")
    row.status, row.student_decided_at = body.status, utcnow()
    audit(db, user.id, "referral.student_" + body.status, "referral", row.id)
    db.commit()
    return {"id": row.id, "status": row.status, "automatic_contact": False}
