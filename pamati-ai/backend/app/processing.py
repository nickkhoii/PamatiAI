"""The only supported adapter execution boundary; consent is checked before and after work.

Adapters receive only references in a saved, consented input manifest. No real model is
loaded by this module. Call from a worker-owned Session, not inside an API transaction.
"""

from dataclasses import dataclass

from app.auth_dependencies import audit
from app.models import (
    AudioAnalysis,
    InteractionSession,
    Message,
    ModelInference,
    MultimodalAnalysis,
    TextAnalysis,
    VisualAnalysis,
    utcnow,
)
from app.persistence import ConsentDenied, current_consent


@dataclass(frozen=True)
class ProcessingInput:
    inference_id: str
    consent_receipt_id: str
    modality: str
    payload_references: dict[str, str]


def permitted_job(db, row):
    receipt = current_consent(db, row.student_id)
    interaction = db.get(InteractionSession, row.session_id)
    inputs = row.input_modalities
    if row.message_id:
        message = db.get(Message, row.message_id, populate_existing=True)
        if not message or message.deleted_at:
            raise ConsentDenied("Message is unavailable")
    if inputs is None and row.modality != "multimodal":
        inputs = [row.modality]  # Legacy single-modality jobs are still explicit.
    if (
        row.deleted_at
        or not interaction
        or interaction.deleted_at
        or interaction.conversation.deleted_at
        or receipt.id != row.consent_record_id
        or not inputs
        or len(inputs) != len(set(inputs))
        or (row.modality != "multimodal" and inputs != [row.modality])
        or any(
            m not in {"text", "audio", "visual"} or not getattr(receipt, f"{m}_processing")
            for m in inputs
        )
    ):
        raise ConsentDenied("Current consent does not authorize this job")
    return list(inputs)


def run_analysis(db, inference_id, adapter, payload_references):
    """Return stored analysis ID, or None when consent changed; never publish revoked results."""
    row = db.get(ModelInference, inference_id)
    if not row:
        raise ValueError("Unknown job")
    # Lock student before job, consistently with consent changes.
    try:
        inputs = permitted_job(db, row)
        db.refresh(row, with_for_update=True)
        if row.processing_status != "pending":
            return None
        if set(payload_references) != set(inputs):
            raise ConsentDenied("Payload references do not match consented inputs")
    except ConsentDenied:
        db.refresh(row, with_for_update=True)
        if row.processing_status in {"pending", "running"}:
            row.processing_status = "cancelled"
        audit(db, None, "processing.consent_denied", "inference", row.id, "denied")
        db.commit()
        return None
    row.processing_status, row.started_at = "running", utcnow()
    sample = ProcessingInput(
        row.id, row.consent_record_id, row.modality, {m: payload_references[m] for m in inputs}
    )
    db.commit()  # Permit withdrawal while an external adapter is running.
    try:
        result = adapter.analyze(sample)
    except Exception:  # noqa: BLE001 -- isolate adapters; never expose payloads in errors
        db.rollback()
        row = db.get(ModelInference, inference_id)
        try:
            permitted_job(db, row)
        except ConsentDenied:
            pass
        db.refresh(row, with_for_update=True)
        if row.processing_status == "running":
            row.processing_status, row.error_code = "failed", "adapter_failed"
        audit(db, None, "processing.adapter_failed", "inference", row.id, "failure")
        db.commit()
        return None
    db.expire_all()
    row = db.get(ModelInference, inference_id)
    try:
        permitted_job(db, row)
        db.refresh(row, with_for_update=True)
        if row.processing_status != "running":
            raise ConsentDenied("Job was cancelled")
    except ConsentDenied:
        if row.processing_status in {"pending", "running"}:
            row.processing_status = "cancelled"
        audit(db, None, "processing.result_discarded", "inference", row.id, "denied")
        db.commit()
        return None
    row.processing_status, row.completed_at = (
        ("abstained" if getattr(result, "abstained", False) else "completed"),
        utcnow(),
    )
    classes = {
        "text": TextAnalysis,
        "audio": AudioAnalysis,
        "visual": VisualAnalysis,
        "multimodal": MultimodalAnalysis,
    }
    values = {
        "inference_id": row.id,
        "modality": row.modality,
        "labels": result.labels,
        "limitations": list(result.limitations),
    }
    if row.modality == "multimodal":
        values.update(
            fusion_strategy_version=row.adapter_version,
            missing_modalities=[m for m in ("text", "audio", "visual") if m not in inputs],
        )
    if row.modality in {"text", "audio"} and hasattr(result, "uncertainty"):
        row.confidence = result.confidence
        row.uncertainty = result.uncertainty
        row.uncertainty_method = result.uncertainty_method
        if row.modality == "text":
            values["language"] = result.language
        else:
            values["duration_seconds"] = result.duration_seconds
    db.flush()
    db.add(classes[row.modality](**values))
    audit(db, None, "processing.completed", "inference", row.id)
    db.commit()
    return row.id
