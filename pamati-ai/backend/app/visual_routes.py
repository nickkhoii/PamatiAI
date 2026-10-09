"""Explicit visual uploads, independently consented; no automatic camera capture."""

import base64
import binascii
import json

from ai.visual.validation import EncodedFrame, InvalidVisualInput, validate_frames
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app import config
from app.auth_dependencies import DB, CurrentUser, audit, authorize_student, throttle
from app.models import InteractionSession, ModelInference
from app.persistence import ConsentDenied
from app.retention import retained
from app.visual_analysis import analyze_visual, authorize_visual, result_view

router = APIRouter(prefix="/api/v1", tags=["optional visual expression research"])


def parse_frames(data, content_type):
    if content_type in {"image/bmp", "image/x-ms-bmp"}:
        return (EncodedFrame(bytes(data)),)
    try:
        envelope = json.loads(data)
        if (not isinstance(envelope, dict) or set(envelope) != {"frames"}
                or not isinstance(envelope["frames"], list)
                or not 1 <= len(envelope["frames"]) <= config.get_settings().visual_max_input_frames):
            raise InvalidVisualInput("Invalid frame envelope")
        frames = []
        for frame in envelope["frames"]:
            if (not isinstance(frame, dict) or set(frame) != {"bmp_base64", "timestamp_seconds"}
                    or not isinstance(frame["bmp_base64"], str)):
                raise InvalidVisualInput("Use base64 BMP pixels and timestamps only")
            frames.append(EncodedFrame(base64.b64decode(frame["bmp_base64"], validate=True),
                                       frame["timestamp_seconds"]))
        return tuple(frames)
    except (ValueError, TypeError, KeyError, RecursionError, binascii.Error) as exc:
        raise InvalidVisualInput("Invalid visual frame envelope") from exc


@router.post("/sessions/{session_id}/visual-analyses", status_code=201)
async def upload_visual(session_id: str, request: Request, db: DB, user: CurrentUser):
    interaction = db.get(InteractionSession, session_id)
    if not interaction or interaction.deleted_at:
        raise HTTPException(404, "Session not found")
    authorize_student(db, user, "conversation:manage", interaction.student_id)
    throttle(db, request, "visual.upload", user.id, ip_limit=30, subject_limit=10)
    try:
        authorize_visual(db, session_id, user.id)
    except ConsentDenied as exc:
        raise HTTPException(409, str(exc)) from None
    db.commit()
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in {"image/bmp", "image/x-ms-bmp", "application/json"}:
        raise HTTPException(415, "Upload a BMP frame or a JSON frame sequence")
    maximum = config.get_settings().visual_max_bytes
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > maximum:
            raise HTTPException(413, "Visual upload exceeds the configured limit")
        data.extend(chunk)
    if not data:
        raise HTTPException(422, "Visual upload is empty")
    try:
        # Recheck before parsing a received sequence; inference rechecks before media work.
        authorize_visual(db, session_id, user.id)
        frames = parse_frames(data, content_type)
        settings = config.get_settings()
        validate_frames(frames, max_bytes=maximum, max_pixels=settings.visual_max_pixels,
                        max_frames=settings.visual_max_input_frames, max_seconds=settings.visual_max_seconds)
        db.commit()
        inference_id = await run_in_threadpool(
            analyze_visual, db, session_id=session_id, student_id=user.id, frames=frames,
        )
    except ConsentDenied as exc:
        raise HTTPException(409, str(exc)) from None
    except InvalidVisualInput:
        raise HTTPException(422, "Invalid visual frame envelope") from None
    row = db.get(ModelInference, inference_id, populate_existing=True)
    result = result_view(db, row)
    db.commit()
    return result


@router.get("/visual-analyses/{inference_id}")
def get_visual_analysis(inference_id: str, db: DB, user: CurrentUser):
    row = db.get(ModelInference, inference_id)
    if not retained(db, row, "analysis") or row.modality != "visual":
        raise HTTPException(404, "Visual analysis not found")
    authorize_student(db, user, "history:read", row.student_id)
    interaction = db.get(InteractionSession, row.session_id)
    if not interaction or interaction.deleted_at or not retained(db, interaction.conversation, "conversations"):
        raise HTTPException(404, "Session not found")
    result = result_view(db, row)
    audit(db, user.id, "visual_analysis.read", "inference", row.id)
    db.commit()
    return result
