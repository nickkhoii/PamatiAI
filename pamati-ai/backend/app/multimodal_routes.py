from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from app.auth_dependencies import DB, CurrentUser, audit, authorize_student, throttle
from app.auth_routes import Input
from app.models import InteractionSession, ModelInference
from app.multimodal_fusion import analyze_fusion, result_view
from app.persistence import ConsentDenied
from app.retention import retained

router = APIRouter(prefix="/api/v1", tags=["experimental multimodal fusion"])


class FusionRequest(Input):
    source_inference_ids: list[UUID] = Field(min_length=1, max_length=3)


@router.post("/sessions/{session_id}/multimodal-analyses", status_code=201)
def submit_fusion(session_id: str, body: FusionRequest, request: Request, db: DB, user: CurrentUser):
    interaction = db.get(InteractionSession, session_id)
    if not interaction or interaction.deleted_at:
        raise HTTPException(404, "Session not found")
    authorize_student(db, user, "conversation:manage", interaction.student_id)
    throttle(db, request, "fusion.submit", user.id, ip_limit=30, subject_limit=10)
    try:
        inference_id = analyze_fusion(db, session_id=session_id, student_id=user.id,
                                      source_inference_ids=[str(value) for value in body.source_inference_ids])
    except ConsentDenied as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    row = db.get(ModelInference, inference_id, populate_existing=True)
    result = result_view(db, row)
    db.commit()
    return result


@router.get("/multimodal-analyses/{inference_id}")
def get_fusion(inference_id: str, db: DB, user: CurrentUser):
    row = db.get(ModelInference, inference_id)
    if not retained(db, row, "analysis") or row.modality != "multimodal":
        raise HTTPException(404, "Multimodal analysis not found")
    authorize_student(db, user, "history:read", row.student_id)
    interaction = db.get(InteractionSession, row.session_id)
    if not interaction or interaction.deleted_at or not retained(db, interaction.conversation, "conversations"):
        raise HTTPException(404, "Session not found")
    result = result_view(db, row)
    audit(db, user.id, "multimodal_analysis.read", "inference", row.id)
    db.commit()
    return result
