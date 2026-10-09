"""Optional explicit uploads; never activates a microphone or implicitly analyzes text turns."""

from ai.audio.validation import InvalidAudio, validate_audio
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app import config
from app.audio_analysis import analyze_audio, authorize_audio, result_view
from app.auth_dependencies import DB, CurrentUser, audit, authorize_student, throttle
from app.models import InteractionSession, ModelInference
from app.persistence import ConsentDenied
from app.retention import retained

router = APIRouter(prefix="/api/v1", tags=["optional audio research"])


@router.post("/sessions/{session_id}/audio-analyses", status_code=201)
async def upload_audio(session_id: str, request: Request, db: DB, user: CurrentUser):
    interaction = db.get(InteractionSession, session_id)
    if not interaction or interaction.deleted_at:
        raise HTTPException(404, "Session not found")
    authorize_student(db, user, "conversation:manage", interaction.student_id)
    throttle(db, request, "audio.upload", user.id, ip_limit=30, subject_limit=10)
    try:
        authorize_audio(db, session_id, user.id)
    except ConsentDenied as exc:
        raise HTTPException(409, str(exc)) from None
    db.commit()  # Do not hold consent locks while receiving a potentially slow upload.
    if request.headers.get("content-type", "").split(";")[0].lower() not in {
        "audio/wav", "audio/x-wav", "audio/wave"
    }:
        raise HTTPException(415, "Upload a PCM WAV request body")
    maximum = config.get_settings().audio_max_bytes
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > maximum:
            raise HTTPException(413, "Audio upload exceeds the configured limit")
        data.extend(chunk)
    if not data:
        raise HTTPException(422, "Audio upload is empty")
    try:
        authorize_audio(db, session_id, user.id)
        await run_in_threadpool(validate_audio, bytes(data), max_bytes=maximum,
                                max_seconds=config.get_settings().audio_max_seconds)
        inference_id = await run_in_threadpool(
            analyze_audio, db, session_id=session_id, student_id=user.id, data=bytes(data),
        )
    except ConsentDenied as exc:
        raise HTTPException(409, str(exc)) from None
    except InvalidAudio:
        raise HTTPException(422, "Invalid PCM WAV upload") from None
    row = db.get(ModelInference, inference_id, populate_existing=True)
    result = result_view(db, row)
    db.commit()
    return result


@router.get("/audio-analyses/{inference_id}")
def get_audio_analysis(inference_id: str, db: DB, user: CurrentUser):
    row = db.get(ModelInference, inference_id)
    if not retained(db, row, "analysis") or row.modality != "audio":
        raise HTTPException(404, "Audio analysis not found")
    authorize_student(db, user, "history:read", row.student_id)
    interaction = db.get(InteractionSession, row.session_id)
    if not interaction or interaction.deleted_at or not retained(db, interaction.conversation, "conversations"):
        raise HTTPException(404, "Session not found")
    result = result_view(db, row)
    audit(db, user.id, "audio_analysis.read", "inference", row.id)
    db.commit()
    return result
