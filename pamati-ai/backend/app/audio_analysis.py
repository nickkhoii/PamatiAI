"""Consent-controlled execution and independent persistence of acoustic research features."""

from datetime import timedelta

from ai.audio.features import CONFIGURATION
from ai.audio.features import VERSION as FEATURE_VERSION
from ai.audio.files import RecordingStore
from ai.audio.registry import registry
from ai.audio.service import AudioInferenceService
from ai.audio.validation import VERSION as VALIDATION_VERSION
from sqlalchemy import select

from app import config
from app.auth_dependencies import audit
from app.models import (
    AudioAnalysis,
    Conversation,
    InteractionSession,
    MediaAsset,
    ModelInference,
    ModelVersion,
    utcnow,
)
from app.persistence import ConsentDenied, create_inference, current_consent, retain_media
from app.processing import run_analysis
from app.retention import retained, retention_policy


def disclosure():
    settings = config.get_settings()
    if not settings.audio_analysis_enabled:
        return {"enabled": False}
    meta = registry.resolve(settings.audio_analysis_model).metadata
    return {
        "enabled": True, "processor": "PamatiAI server", "model": meta.identifier,
        "model_version": meta.version, "adapter_version": meta.adapter_version,
        "model_configuration": meta.configuration, "feature_version": FEATURE_VERSION,
        "feature_configuration": CONFIGURATION, "validation_version": VALIDATION_VERSION,
        "minimum_confidence": settings.audio_analysis_minimum_confidence,
        "maximum_bytes": settings.audio_max_bytes, "maximum_seconds": settings.audio_max_seconds,
        "raw_storage_enabled": settings.allow_raw_media_storage,
    }


def authorize_audio(db, session_id, student_id):
    """Call before reading uploads or resolving/decoding audio payloads."""
    from app.consent_policy import POLICY_VERSION

    if not config.get_settings().audio_analysis_enabled:
        raise ConsentDenied("Optional audio analysis is disabled")
    receipt = current_consent(db, student_id)
    if not receipt.audio_processing:
        raise ConsentDenied("Active audio-processing consent is required")
    if (receipt.policy_version != POLICY_VERSION or not receipt.disclosure_snapshot
            or receipt.disclosure_snapshot.get("audio_analysis_processing") != disclosure()):
        raise ConsentDenied("Review the current audio processor disclosure before uploading")
    interaction = db.scalar(
        select(InteractionSession).where(InteractionSession.id == session_id)
        .with_for_update().execution_options(populate_existing=True)
    )
    if (not interaction or interaction.student_id != student_id or interaction.deleted_at
            or interaction.ended_at):
        raise ConsentDenied("An active student-owned interaction session is required")
    conversation = db.scalar(
        select(Conversation).where(Conversation.id == interaction.conversation_id)
        .with_for_update().execution_options(populate_existing=True)
    )
    if not retained(db, conversation, "conversations") or conversation.status != "open":
        raise ConsentDenied("Conversation is unavailable")
    return receipt


class AudioAdapter:
    def __init__(self, db, session_id, student_id, receipt_id, data, service, processor):
        self.db, self.session_id, self.student_id = db, session_id, student_id
        self.receipt_id, self.data, self.service, self.processor = receipt_id, data, service, processor

    def analyze(self, sample):
        receipt = authorize_audio(self.db, self.session_id, self.student_id)
        if (receipt.id != self.receipt_id or disclosure() != self.processor
                or sample.payload_references != {"audio": sample.inference_id}):
            raise ConsentDenied("Audio job authorization changed")
        self.db.commit()  # Release locks before feature/model execution.
        result = self.service.analyze_bytes(self.data)
        # run_analysis checks receipt again; also discard changed processor configuration.
        if disclosure() != self.processor:
            raise ConsentDenied("Audio processor changed during analysis")
        authorize_audio(self.db, self.session_id, self.student_id)
        return result


def analyze_audio(db, *, session_id, student_id, data):
    receipt = authorize_audio(db, session_id, student_id)
    settings = config.get_settings()
    if not data or len(data) > settings.audio_max_bytes:
        raise ValueError("Audio upload is empty or too large")
    model = registry.resolve(settings.audio_analysis_model)
    meta = model.metadata
    model_config = {"model": meta.configuration, "feature_version": FEATURE_VERSION,
                    "feature_configuration": CONFIGURATION, "validation_version": VALIDATION_VERSION}
    version = db.scalar(select(ModelVersion).where(
        ModelVersion.model_identifier == meta.identifier, ModelVersion.version == meta.version,
        ModelVersion.modality == "audio",
    ))
    if version is None:
        version = ModelVersion(model_identifier=meta.identifier, version=meta.version,
                               modality="audio", configuration=model_config)
        db.add(version)
        db.flush()
    elif version.configuration != model_config:
        raise ValueError("Audio configuration changed without a new model version")
    row = create_inference(
        db, student_id=student_id, session_id=session_id, model_version_id=version.id,
        preprocessing_version=VALIDATION_VERSION, adapter_version=meta.adapter_version,
    )
    inference_id, receipt_id = row.id, receipt.id
    service = AudioInferenceService(
        model, minimum_confidence=settings.audio_analysis_minimum_confidence,
        temporary_directory=settings.audio_temporary_directory or None,
        max_bytes=settings.audio_max_bytes, max_seconds=settings.audio_max_seconds,
    )
    adapter = AudioAdapter(db, session_id, student_id, receipt_id, data, service, disclosure())
    audit(db, student_id, "audio.submitted", "inference", inference_id)
    db.commit()
    saved = run_analysis(db, inference_id, adapter, {"audio": inference_id})
    if saved:
        retain_recording(db, inference_id, data)
    return inference_id


def retain_recording(db, inference_id, data):
    """Optional raw storage requires environment, database gate and separate user permission."""
    settings = config.get_settings()
    if not settings.allow_raw_media_storage:
        return
    row = db.get(ModelInference, inference_id)
    try:
        receipt = authorize_audio(db, row.session_id, row.student_id)
        if receipt.id != row.consent_record_id or not receipt.retain_audio:
            return
        store = RecordingStore(settings.audio_storage_directory)
        key = store.new_key()
        asset = retain_media(
            db, settings, student_id=row.student_id, session_id=row.session_id,
            modality="audio", storage_reference=key,
            expires_at=utcnow() + timedelta(hours=retention_policy(db).raw_media_hours),
        )
    except ConsentDenied:
        db.rollback()
        return
    written = False
    try:
        store.write(key, data)
        written = True
        audit(db, row.student_id, "audio.raw_retained", "media_asset", asset.id)
        db.commit()
    except Exception:
        db.rollback()
        if written:
            store.delete(key)
        raise


def purge_expired_recordings(db):
    """Run periodically and after withdrawals: python -m app.audio_analysis."""
    store = RecordingStore(config.get_settings().audio_storage_directory)
    now = utcnow()
    count = 0
    cap = timedelta(hours=retention_policy(db).raw_media_hours)
    for asset in db.scalars(select(MediaAsset).where(
        MediaAsset.modality == "audio", MediaAsset.purged_at.is_(None),
    ).with_for_update()):
        if (asset.deleted_at or min(asset.expires_at, asset.created_at + cap) <= now):
            store.delete(asset.storage_reference)
            asset.purged_at = now  # Only mark physical deletion after the storage call succeeds.
            audit(db, None, "audio.raw_purged", "media_asset", asset.id)
            count += 1
    db.commit()
    return count


def result_view(db, row):
    from app.models import ConsentRecord

    model = db.get(ModelVersion, row.model_version_id)
    analysis = db.get(AudioAnalysis, row.id)
    receipt = db.get(ConsentRecord, row.consent_record_id)
    return {
        "analysis_id": row.id, "session_id": row.session_id, "message_id": row.message_id,
        "model_id": model.id, "model": model.model_identifier, "model_version": model.version,
        "feature_version": model.configuration.get("feature_version"),
        "validation_version": row.preprocessing_version, "adapter_version": row.adapter_version,
        "consent_record_id": row.consent_record_id,
        "consent_state": {"audio_processing_at_submission": receipt.audio_processing,
                          "retain_audio_at_submission": receipt.retain_audio,
                          "receipt_version": receipt.version,
                          "policy_version": receipt.policy_version,
                          "withdrawn_at": receipt.withdrawn_at},
        "status": row.processing_status, "created_at": row.created_at,
        "started_at": row.started_at, "completed_at": row.completed_at,
        "confidence": row.confidence, "uncertainty": row.uncertainty,
        "uncertainty_method": row.uncertainty_method, "error_code": row.error_code,
        "duration_seconds": analysis.duration_seconds if analysis else None,
        "result": analysis.labels if analysis else None,
        "limitations": analysis.limitations if analysis else [],
    }


if __name__ == "__main__":
    from app.db import SessionLocal

    with SessionLocal() as session:
        print(f"Purged {purge_expired_recordings(session)} expired audio recordings")
