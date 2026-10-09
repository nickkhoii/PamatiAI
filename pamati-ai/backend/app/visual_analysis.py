"""Optional visual job bridge; persist only bounded observation summaries, never raw media."""

from ai.visual.normalization import VERSION as SCHEMA_VERSION
from ai.visual.registry import extractors, models
from ai.visual.sampling import VERSION as SAMPLING_VERSION
from ai.visual.service import VisualInferenceService
from ai.visual.validation import VERSION as VALIDATION_VERSION
from sqlalchemy import select

from app import config
from app.auth_dependencies import audit
from app.models import (
    ConsentRecord,
    Conversation,
    InteractionSession,
    ModelVersion,
    VisualAnalysis,
)
from app.persistence import ConsentDenied, create_inference, current_consent
from app.processing import run_analysis
from app.retention import retained


def configured_adapters():
    settings = config.get_settings()
    return extractors.resolve(settings.visual_feature_extractor), models.resolve(settings.visual_analysis_model)


def disclosure():
    settings = config.get_settings()
    if not settings.visual_analysis_enabled:
        return {"enabled": False}
    extractor, model = configured_adapters()
    return {
        "enabled": True, "processor": "PamatiAI server", "raw_retention": False,
        "model": model.metadata.identifier, "model_version": model.metadata.version,
        "model_configuration": model.metadata.configuration,
        "feature_extractor": extractor.metadata.identifier, "feature_version": extractor.metadata.version,
        "feature_configuration": extractor.metadata.configuration,
        "schema_version": SCHEMA_VERSION, "validation_version": VALIDATION_VERSION,
        "sampling_version": SAMPLING_VERSION, "sample_count": settings.visual_sample_count,
        "minimum_confidence": settings.visual_analysis_minimum_confidence,
        "maximum_bytes": settings.visual_max_bytes, "maximum_pixels": settings.visual_max_pixels,
        "maximum_input_frames": settings.visual_max_input_frames,
        "maximum_seconds": settings.visual_max_seconds,
    }


def authorize_visual(db, session_id, student_id):
    """Authorize before consuming request bodies, creating media files or decoding frames."""
    from app.consent_policy import POLICY_VERSION

    if not config.get_settings().visual_analysis_enabled:
        raise ConsentDenied("Optional visual analysis is disabled")
    receipt = current_consent(db, student_id)
    if not receipt.visual_processing:
        raise ConsentDenied("Explicit active visual-processing consent is required")
    if (receipt.policy_version != POLICY_VERSION or not receipt.disclosure_snapshot
            or receipt.disclosure_snapshot.get("visual_analysis_processing") != disclosure()):
        raise ConsentDenied("Review the current visual processor disclosure before uploading")
    interaction = db.scalar(select(InteractionSession).where(InteractionSession.id == session_id)
                            .with_for_update().execution_options(populate_existing=True))
    if (not interaction or interaction.student_id != student_id or interaction.deleted_at
            or interaction.ended_at):
        raise ConsentDenied("An active student-owned interaction session is required")
    conversation = db.scalar(select(Conversation).where(Conversation.id == interaction.conversation_id)
                             .with_for_update().execution_options(populate_existing=True))
    if not retained(db, conversation, "conversations") or conversation.status != "open":
        raise ConsentDenied("Conversation is unavailable")
    return receipt


class VisualAdapter:
    def __init__(self, db, session_id, student_id, receipt_id, frames, service, processor):
        self.db, self.session_id, self.student_id = db, session_id, student_id
        self.receipt_id, self.frames, self.service, self.processor = receipt_id, frames, service, processor

    def analyze(self, sample):
        receipt = authorize_visual(self.db, self.session_id, self.student_id)
        if (receipt.id != self.receipt_id or disclosure() != self.processor
                or sample.payload_references != {"visual": sample.inference_id}):
            raise ConsentDenied("Visual job authorization changed")
        self.db.commit()  # Allow refusal/withdrawal while adapters are executing.
        result = self.service.analyze_frames(self.frames)
        if disclosure() != self.processor:
            raise ConsentDenied("Visual processor changed during analysis")
        authorize_visual(self.db, self.session_id, self.student_id)
        return result


def analyze_visual(db, *, session_id, student_id, frames):
    receipt = authorize_visual(db, session_id, student_id)
    settings = config.get_settings()
    extractor, model = configured_adapters()
    meta = model.metadata
    configuration = {
        "model": meta.configuration, "feature_extractor": extractor.metadata.identifier,
        "feature_version": extractor.metadata.version, "feature_configuration": extractor.metadata.configuration,
        "schema_version": SCHEMA_VERSION, "validation_version": VALIDATION_VERSION,
        "sampling_version": SAMPLING_VERSION,
    }
    query = select(ModelVersion).where(
        ModelVersion.model_identifier == meta.identifier, ModelVersion.version == meta.version,
        ModelVersion.modality == "visual",
    )
    version = db.scalar(query)
    if version is None:
        version = ModelVersion(model_identifier=meta.identifier, version=meta.version,
                               modality="visual", configuration=configuration)
        db.add(version)
        db.flush()
    elif version.configuration != configuration:
        raise ValueError("Visual pipeline changed without a new model version")
    row = create_inference(
        db, student_id=student_id, session_id=session_id, model_version_id=version.id,
        preprocessing_version=VALIDATION_VERSION, adapter_version=SCHEMA_VERSION,
    )
    inference_id = row.id
    service = VisualInferenceService(
        extractor, model, temporary_directory=settings.visual_temporary_directory or None,
        sample_count=settings.visual_sample_count, minimum_confidence=settings.visual_analysis_minimum_confidence,
        max_bytes=settings.visual_max_bytes, max_pixels=settings.visual_max_pixels,
        max_frames=settings.visual_max_input_frames, max_seconds=settings.visual_max_seconds,
    )
    adapter = VisualAdapter(db, session_id, student_id, receipt.id, frames, service, disclosure())
    audit(db, student_id, "visual.submitted", "inference", inference_id)
    db.commit()
    run_analysis(db, inference_id, adapter, {"visual": inference_id})
    # No MediaAsset/raw recording writes, even when generic raw-media settings are enabled.
    return inference_id


def result_view(db, row):
    model = db.get(ModelVersion, row.model_version_id)
    analysis = db.get(VisualAnalysis, row.id)
    receipt = db.get(ConsentRecord, row.consent_record_id)
    return {
        "analysis_id": row.id, "session_id": row.session_id, "message_id": row.message_id,
        "model_id": model.id, "model": model.model_identifier, "model_version": model.version,
        "feature_extractor": model.configuration.get("feature_extractor"),
        "feature_version": model.configuration.get("feature_version"),
        "validation_version": row.preprocessing_version, "adapter_version": row.adapter_version,
        "consent_record_id": row.consent_record_id,
        "consent_state": {"visual_processing_at_submission": receipt.visual_processing,
                          "receipt_version": receipt.version, "policy_version": receipt.policy_version,
                          "withdrawn_at": receipt.withdrawn_at},
        "status": row.processing_status, "created_at": row.created_at,
        "started_at": row.started_at, "completed_at": row.completed_at,
        "confidence": row.confidence, "uncertainty": row.uncertainty,
        "uncertainty_method": row.uncertainty_method, "error_code": row.error_code,
        "sampled_frame_count": analysis.sampled_frame_count if analysis else None,
        "result": analysis.labels if analysis else None,
        "limitations": analysis.limitations if analysis else [], "raw_retained": False,
    }
