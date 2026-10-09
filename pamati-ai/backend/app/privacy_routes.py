"""Student onboarding, record inventory and transparent institutional retention restrictions."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import func, select

from app.auth_dependencies import DB, CurrentUser, audit, authorize_student, require_role
from app.auth_routes import AccountManager, Admin, Input
from app.consent_policy import POLICY_VERSION, policy_document
from app.models import (
    ConsentRecord,
    Conversation,
    DataControlRequest,
    MediaAsset,
    ModelInference,
    ResearchDatasetRecord,
    RetentionHold,
    SentimentTrend,
    StudentProfile,
    User,
    WellbeingCheckIn,
    utcnow,
)
from app.resource_routes import receipt_view
from app.retention import Category, active_holds, deadline, hold_view, retention_policy

router = APIRouter(prefix="/api/v1", tags=["student privacy"])
Student = Annotated[User, Depends(require_role("STUDENT"))]


@router.get("/me/onboarding")
def onboarding(db: DB, user: Student):
    authorize_student(db, user, "consent:manage", user.id)
    receipt = db.scalar(
        select(ConsentRecord)
        .where(ConsentRecord.student_id == user.id)
        .order_by(ConsentRecord.version.desc())
        .limit(1)
    )
    return {
        "policy": policy_document(),
        "retention": retention_policy(db).model_dump(),
        "consent": receipt_view(receipt),
        "completed": bool(
            receipt
            and not receipt.withdrawn_at
            and receipt.disclosure_snapshot
            and receipt.policy_version == POLICY_VERSION
            and receipt.disclosure_snapshot.get("conversation_processing") == policy_document()["conversation_processing"]
            and receipt.disclosure_snapshot.get("text_analysis_processing", {"models": []})
            == policy_document()["text_analysis_processing"]
            and receipt.disclosure_snapshot.get("safety_processing") == policy_document()["safety_processing"]
            and receipt.disclosure_snapshot.get("audio_analysis_processing", {"enabled": False})
            == policy_document()["audio_analysis_processing"]
            and (
                not receipt.visual_processing
                or receipt.disclosure_snapshot.get("visual_analysis_processing", {"enabled": False})
                == policy_document()["visual_analysis_processing"]
            )
        ),
        "raw_retention_enabled": False,
    }  # This onboarding UI never offers raw recording retention.


@router.get("/students/{student_id}/consent/history")
def consent_history(student_id: str, db: DB, user: CurrentUser, offset: int = 0):
    authorize_student(db, user, "consent:manage", student_id)
    rows = db.scalars(
        select(ConsentRecord)
        .where(ConsentRecord.student_id == student_id)
        .order_by(ConsentRecord.version.desc())
        .offset(max(offset, 0))
        .limit(50)
    )
    result = [receipt_view(r) for r in rows]
    audit(db, user.id, "consent.history_read", "student", student_id)
    db.commit()
    return result


@router.get("/students/{student_id}/privacy")
def privacy(student_id: str, db: DB, user: CurrentUser):
    authorize_student(db, user, "privacy:manage", student_id)
    result = {
        "retention": retention_policy(db).model_dump(),
        "holds": [hold_view(h) for h in active_holds(db, student_id)],
        "counts": {},
    }
    for name, cls in [
        ("conversations", Conversation),
        ("analysis", ModelInference),
        ("trends", SentimentTrend),
        ("media", MediaAsset),
        ("research", ResearchDatasetRecord),
        ("consent", ConsentRecord),
        ("check_ins", WellbeingCheckIn),
    ]:
        result["counts"][name] = db.scalar(
            select(func.count()).select_from(cls).where(cls.student_id == student_id)
        )
    audit(db, user.id, "privacy.inventory_read", "student", student_id)
    db.commit()
    return result


@router.get("/students/{student_id}/records")
def records(student_id: str, category: Category, db: DB, user: CurrentUser, offset: int = 0):
    authorize_student(db, user, "privacy:manage", student_id)
    cls = {
        "conversations": Conversation,
        "check_ins": WellbeingCheckIn,
        "analysis": ModelInference,
        "research": ResearchDatasetRecord,
        "consent_audit": ConsentRecord,
    }[category]
    rows = list(
        db.scalars(
            select(cls)
            .where(cls.student_id == student_id)
            .order_by(cls.created_at.desc(), cls.id)
            .offset(max(0, offset))
            .limit(51)
        )
    )
    result = []
    for row in rows[:50]:
        snapshot = row.retention_snapshot if category in {"conversations", "check_ins"} else None
        if category == "consent_audit" and row.disclosure_snapshot:
            snapshot = row.disclosure_snapshot.get("retention")
        if category in {"analysis", "research"}:
            receipt = db.get(ConsentRecord, row.consent_record_id)
            if receipt and receipt.disclosure_snapshot:
                snapshot = receipt.disclosure_snapshot.get("retention")
        item = {
            "id": row.id,
            "created_at": row.created_at,
            "retention_until": deadline(
                db, student_id, category, row.created_at, snapshot=snapshot
            ),
        }
        if category == "conversations":
            item.update(status=row.status, hidden=row.deleted_at is not None)
        elif category == "check_ins":
            item.update(status=row.feeling, hidden=row.deleted_at is not None)
        elif category == "analysis":
            item.update(modality=row.modality, status=row.processing_status)
        elif category == "research":
            item.update(
                dataset_identifier=row.dataset_identifier, revoked=row.revoked_at is not None
            )
        else:
            item.update(
                version=row.version,
                policy_version=row.policy_version,
                withdrawn_at=row.withdrawn_at,
            )
        result.append(item)
    audit(db, user.id, "privacy.records_read", "student", student_id)
    db.commit()
    return {
        "records": result,
        "next_offset": offset + 50 if len(rows) > 50 else None,
        "category": category,
    }


class HoldInput(Input):
    category: Category
    reason: str = Field(min_length=10, max_length=500)
    legal_basis: str = Field(min_length=10, max_length=255)
    expires_at: datetime


@router.post("/admin/students/{student_id}/retention-holds", status_code=201)
def create_hold(student_id: str, body: HoldInput, db: DB, admin: Admin, manager: AccountManager):
    student = db.get(StudentProfile, student_id)
    if not student or student.deleted_at:
        raise HTTPException(404, "Student not found")
    if body.expires_at.tzinfo is None:
        raise HTTPException(422, "Provide a timezone-aware expiry")
    expiry = body.expires_at.astimezone(UTC).replace(tzinfo=None)
    if not utcnow() < expiry <= utcnow() + timedelta(days=3650):
        raise HTTPException(422, "Hold expiry must be in the future and within ten years")
    row = RetentionHold(
        student_id=student_id,
        category=body.category,
        reason=body.reason,
        legal_basis=body.legal_basis,
        expires_at=expiry,
        created_by=admin.id,
    )
    db.add(row)
    db.flush()
    audit(db, admin.id, "privacy.hold_created", "retention_hold", row.id)
    db.commit()
    return hold_view(row)


@router.delete("/admin/retention-holds/{hold_id}", status_code=204)
def release_hold(hold_id: str, db: DB, admin: Admin, manager: AccountManager):
    row = db.get(RetentionHold, hold_id)
    if not row:
        raise HTTPException(404, "Hold not found")
    row.released_at = utcnow()
    audit(db, admin.id, "privacy.hold_released", "retention_hold", row.id)
    db.commit()


class RequestDecision(Input):
    # No completion option: only a verified fulfillment worker may claim export/deletion completion.
    status: str = Field(pattern="^(in_review|deferred)$")
    reason: str = Field(min_length=10, max_length=500)


@router.patch("/admin/data-controls/{request_id}")
def review_request(
    request_id: str, body: RequestDecision, db: DB, admin: Admin, manager: AccountManager
):
    row = db.scalar(
        select(DataControlRequest).where(DataControlRequest.id == request_id).with_for_update()
    )
    if not row:
        raise HTTPException(404, "Request not found")
    if body.status == "deferred" and (
        row.kind != "erasure" or not active_holds(db, row.student_id)
    ):
        raise HTTPException(409, "Deferral requires an active documented retention hold")
    row.status, row.decision_reason, row.decided_at = body.status, body.reason, utcnow()
    if body.status == "deferred":
        row.review_due_at = min(h.expires_at for h in active_holds(db, row.student_id))
    audit(db, admin.id, "privacy.request_reviewed", "data_control", row.id)
    db.commit()
    return {
        "id": row.id,
        "status": row.status,
        "decision_reason": row.decision_reason,
        "review_due_at": row.review_due_at,
    }


@router.get("/admin/data-controls")
def pending_requests(db: DB, admin: Admin, manager: AccountManager):
    rows = db.scalars(select(DataControlRequest).order_by(DataControlRequest.created_at).limit(100))
    result = [
        {
            "id": r.id,
            "student_id": r.student_id,
            "kind": r.kind,
            "status": r.status,
            "review_due_at": r.review_due_at,
        }
        for r in rows
    ]
    audit(db, admin.id, "privacy.request_queue_read", "data_control")
    db.commit()
    return result
