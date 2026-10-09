"""Owner-only personal downloads and available analysis records; never research exports."""

import json

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from app.auth_dependencies import DB, CurrentUser, audit, authorize_student, throttle
from app.models import (
    AudioAnalysis,
    ConsentRecord,
    Conversation,
    DataControlRequest,
    InteractionSession,
    Message,
    ModelInference,
    MultimodalAnalysis,
    SupportRequest,
    TextAnalysis,
    VisualAnalysis,
    WellbeingCheckIn,
    utcnow,
)
from app.resource_routes import receipt_view
from app.retention import retained

router = APIRouter(prefix="/api/v1/students", tags=["personal data access"])
MAX_RECORDS = 10000
MAX_DOWNLOAD_BYTES = 8_000_000


def owner(db, user, student_id):
    authorize_student(db, user, "privacy:manage", student_id)
    if user.id != student_id:
        raise HTTPException(403, "Only the student can download their own data")


def bounded_rows(db, query):
    rows = list(db.scalars(query.limit(MAX_RECORDS + 1)))
    if len(rows) > MAX_RECORDS:
        raise HTTPException(413, "Download is too large; request an institutional export")
    return rows


def analysis_view(db, row):
    cls = {"text": TextAnalysis, "audio": AudioAnalysis, "visual": VisualAnalysis,
           "multimodal": MultimodalAnalysis}[row.modality]
    result = db.get(cls, row.id)
    return {"id": row.id, "session_id": row.session_id, "message_id": row.message_id,
            "modality": row.modality, "status": row.processing_status,
            "created_at": row.created_at, "completed_at": row.completed_at,
            "model": row.model.model_identifier, "model_version": row.model.version,
            "adapter_version": row.adapter_version, "consent_record_id": row.consent_record_id,
            "origin": "AI-generated observation", "result": result.labels if result else None,
            "limitations": result.limitations if result else [], "uncertainty": row.uncertainty}


@router.get("/{student_id}/analyses")
def analyses(student_id: str, db: DB, user: CurrentUser,
             modality: str = Query("", pattern="^(|text|audio|visual|multimodal)$"),
             page: int = Query(1, ge=1, le=5000), limit: int = Query(12, ge=1, le=100)):
    owner(db, user, student_id)
    query = select(ModelInference).where(ModelInference.student_id == student_id,
                                        ModelInference.deleted_at.is_(None))
    if modality:
        query = query.where(ModelInference.modality == modality)
    rows = [r for r in bounded_rows(db, query.order_by(ModelInference.created_at.desc(), ModelInference.id))
            if retained(db, r, "analysis")]
    result = {"items": [analysis_view(db, r) for r in rows[(page - 1) * limit:page * limit]],
              "total": len(rows), "page": page, "limit": limit}
    audit(db, user.id, "privacy.analyses_read", "student", student_id)
    db.commit()
    return result


@router.get("/{student_id}/data-download")
def download(student_id: str, request: Request, db: DB, user: CurrentUser):
    owner(db, user, student_id)
    throttle(db, request, "privacy.download", user.id, ip_limit=20, subject_limit=5)
    # Reauthorize after the rate-limit transaction; no model is executed by a download.
    owner(db, user, student_id)
    payload = {"format_version": "1", "generated_at": utcnow(), "timezone": "UTC",
               "profile": {"id": user.id, "email": user.email, "display_name": user.display_name},
               "scope": "Available student records, not an institutional case-file export",
               "excluded": ["hidden or expired content", "raw media", "credentials and tokens",
                            "professional case notes and internal safety narratives", "backups"],
               "conversations": [], "analyses": [], "check_ins": [], "consent_receipts": [],
               "support_requests": [], "privacy_requests": []}
    conversations = bounded_rows(db, select(Conversation).where(Conversation.student_id == student_id))
    for conversation in conversations:
        if not retained(db, conversation, "conversations"):
            continue
        messages = bounded_rows(db, select(Message).join(InteractionSession,
            Message.session_id == InteractionSession.id).where(
            InteractionSession.conversation_id == conversation.id,
            InteractionSession.student_id == student_id, InteractionSession.deleted_at.is_(None),
            Message.student_id == student_id, Message.deleted_at.is_(None),
            Message.sender.in_(["student", "assistant"])).order_by(Message.created_at, Message.sequence_number))
        payload["conversations"].append({"id": conversation.id, "created_at": conversation.created_at,
            "status": conversation.status, "messages": [{"id": m.id, "sender": m.sender,
            "created_at": m.created_at, "text": m.text_content} for m in messages]})
        if sum(len(c["messages"]) for c in payload["conversations"]) > MAX_RECORDS:
            raise HTTPException(413, "Download is too large; request an institutional export")
    for row in bounded_rows(db, select(ModelInference).where(ModelInference.student_id == student_id)):
        if retained(db, row, "analysis"):
            payload["analyses"].append(analysis_view(db, row))
    for row in bounded_rows(db, select(WellbeingCheckIn).where(WellbeingCheckIn.student_id == student_id)):
        if retained(db, row, "check_ins"):
            payload["check_ins"].append({"id": row.id, "created_at": row.created_at, "feeling": row.feeling})
    for row in bounded_rows(db, select(ConsentRecord).where(ConsentRecord.student_id == student_id)):
        if retained(db, row, "consent_audit"):
            payload["consent_receipts"].append(receipt_view(row))
    for key, cls, fields in [("support_requests", SupportRequest, ("id", "status", "created_at")),
                            ("privacy_requests", DataControlRequest,
                             ("id", "kind", "status", "created_at", "review_due_at", "decision_reason"))]:
        payload[key] = [{field: getattr(r, field) for field in fields} for r in
                        bounded_rows(db, select(cls).where(cls.student_id == student_id))]
    encoded = json.dumps(jsonable_encoder(payload), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_DOWNLOAD_BYTES:
        raise HTTPException(413, "Download is too large; request an institutional export")
    audit(db, user.id, "privacy.downloaded", "student", student_id)
    db.commit()
    return Response(encoded, media_type="application/json", headers={
        "Content-Disposition": 'attachment; filename="pamati-personal-data.json"', "Cache-Control": "no-store"})
