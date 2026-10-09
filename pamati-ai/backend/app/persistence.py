"""Transactional consent-aware writes; callers still need authenticated RBAC checks."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    ConsentRecord,
    InteractionSession,
    MediaAsset,
    ModelInference,
    ModelVersion,
    ResearchDatasetRecord,
    StudentProfile,
    SystemSetting,
    User,
    utcnow,
)
from app.retention import retained, retention_policy

CONSENT_FIELDS = {
    "text_processing",
    "audio_processing",
    "visual_processing",
    "longitudinal_tracking",
    "research_data_use",
    "reviewer_access",
    "retain_audio",
    "retain_visual",
}


class ConsentDenied(ValueError):
    pass


def lock_student(session: Session, student_id: str) -> StudentProfile:
    # Keep lock order consistent with authentication, and use current MySQL locking reads.
    account = session.scalar(
        select(User)
        .where(User.id == student_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if account is None or account.deleted_at or not account.is_active:
        raise ConsentDenied("Student account is unavailable")
    student = session.scalar(
        select(StudentProfile)
        .where(StudentProfile.user_id == student_id, StudentProfile.deleted_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if student is None or student.user.deleted_at or not student.user.is_active:
        raise ConsentDenied("Student account is unavailable")
    return student


def current_consent(session: Session, student_id: str) -> ConsentRecord:
    lock_student(session, student_id)
    receipt = session.scalar(
        select(ConsentRecord)
        .where(ConsentRecord.student_id == student_id)
        .order_by(ConsentRecord.version.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if receipt is None or receipt.withdrawn_at is not None:
        raise ConsentDenied("Active consent is required")
    return receipt


def record_consent(
    session: Session,
    student_id: str,
    policy_version: str,
    *,
    disclosure_snapshot=None,
    **permissions,
):
    lock_student(session, student_id)
    if not policy_version or permissions.keys() - CONSENT_FIELDS:
        raise ValueError("Unknown consent permission or empty policy version")
    if any(type(value) is not bool for value in permissions.values()):
        raise ValueError("Consent values must be explicit booleans")
    for modality in ("audio", "visual"):
        if permissions.get(f"retain_{modality}") and not permissions.get(f"{modality}_processing"):
            raise ConsentDenied("Retention requires modality processing consent")
    previous = session.scalar(
        select(ConsentRecord)
        .where(ConsentRecord.student_id == student_id)
        .order_by(ConsentRecord.version.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    receipt = ConsentRecord(
        student_id=student_id,
        version=previous.version + 1 if previous else 1,
        policy_version=policy_version,
        disclosure_snapshot=disclosure_snapshot,
        **permissions,
    )
    session.add(receipt)
    session.flush()
    if previous:
        invalidate_processing(session, student_id)
    if not permissions.get("research_data_use", False):
        revoke_research(session, student_id)
    expire_unpermitted_media(session, student_id, receipt)
    return receipt


def withdraw_consent(session: Session, student_id: str):
    lock_student(session, student_id)
    receipt = session.scalar(
        select(ConsentRecord)
        .where(ConsentRecord.student_id == student_id)
        .order_by(ConsentRecord.version.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if receipt is None:
        raise ConsentDenied("No consent receipt exists")
    if receipt.withdrawn_at is None:
        receipt.withdrawn_at = utcnow()
    invalidate_processing(session, student_id)
    revoke_research(session, student_id)
    expire_unpermitted_media(session, student_id, None)
    session.flush()
    return receipt


def invalidate_processing(session, student_id):
    pending = session.scalars(
        select(ModelInference)
        .where(
            ModelInference.student_id == student_id,
            ModelInference.processing_status.in_(["pending", "running"]),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    for inference in pending:
        inference.processing_status = "cancelled"


def revoke_research(session, student_id):
    for record in session.scalars(
        select(ResearchDatasetRecord)
        .where(
            ResearchDatasetRecord.student_id == student_id,
            ResearchDatasetRecord.revoked_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ):
        record.revoked_at = utcnow()
    session.flush()


def expire_unpermitted_media(session, student_id, receipt):
    for asset in session.scalars(
        select(MediaAsset)
        .where(MediaAsset.student_id == student_id, MediaAsset.purged_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    ):
        permitted = (
            receipt
            and getattr(receipt, f"{asset.modality}_processing")
            and getattr(receipt, f"retain_{asset.modality}")
        )
        if not permitted:
            asset.expires_at = min(
                asset.expires_at, max(utcnow(), asset.created_at + timedelta(microseconds=1))
            )
    # Expiry schedules storage erasure; do not claim a physical purge without a storage worker.


def create_inference(
    session: Session,
    *,
    student_id: str,
    session_id: str,
    model_version_id: str,
    preprocessing_version: str,
    adapter_version: str,
    message_id: str | None = None,
    input_modalities: list[str] | None = None,
):
    receipt = current_consent(session, student_id)
    interaction = session.get(InteractionSession, session_id)
    model = session.get(ModelVersion, model_version_id)
    if interaction is None or interaction.student_id != student_id or interaction.deleted_at:
        raise ValueError("Interaction session does not belong to active student")
    if not retained(session, interaction.conversation, "conversations"):
        raise ConsentDenied("Conversation is unavailable")
    if model is None:
        raise ValueError("Unknown model version")
    allowed = [
        getattr(receipt, f"{modality}_processing") for modality in ("text", "audio", "visual")
    ]
    if model.modality == "multimodal":
        if not any(allowed):
            raise ConsentDenied("No modalities are consented")
    elif not getattr(receipt, f"{model.modality}_processing"):
        raise ConsentDenied("Modality processing was declined")
    inputs = (
        input_modalities
        if input_modalities is not None
        else (
            [m for m in ("text", "audio", "visual") if getattr(receipt, f"{m}_processing")]
            if model.modality == "multimodal"
            else [model.modality]
        )
    )
    if (
        not inputs
        or len(set(inputs)) != len(inputs)
        or any(m not in {"text", "audio", "visual"} for m in inputs)
        or (model.modality != "multimodal" and inputs != [model.modality])
    ):
        raise ValueError("Invalid input modality manifest")
    if any(not getattr(receipt, f"{m}_processing") for m in inputs):
        raise ConsentDenied("An input modality was declined")
    inference = ModelInference(
        student_id=student_id,
        session_id=session_id,
        message_id=message_id,
        consent_record_id=receipt.id,
        model_version_id=model.id,
        modality=model.modality,
        input_modalities=inputs,
        preprocessing_version=preprocessing_version,
        adapter_version=adapter_version,
    )
    session.add(inference)
    session.flush()
    return inference


def retain_media(
    session: Session,
    settings: Settings,
    *,
    student_id: str,
    session_id: str,
    modality: str,
    storage_reference: str,
    expires_at: datetime,
):
    if not settings.allow_raw_media_storage or modality not in {"audio", "visual"}:
        raise ConsentDenied("Raw media storage is disabled")
    receipt = current_consent(session, student_id)
    gate = session.get(SystemSetting, "raw_media_retention")
    if gate is None or gate.value.get("enabled") is not True:
        raise ConsentDenied("Database media retention gate is disabled")
    if not getattr(receipt, f"{modality}_processing") or not getattr(receipt, f"retain_{modality}"):
        raise ConsentDenied("Explicit modality retention consent is required")
    if expires_at <= utcnow():
        raise ValueError("Media retention must expire in the future")
    if expires_at > utcnow() + timedelta(hours=retention_policy(session).raw_media_hours):
        raise ConsentDenied("Raw media retention exceeds the configured limit")
    asset = MediaAsset(
        student_id=student_id,
        session_id=session_id,
        consent_record_id=receipt.id,
        modality=modality,
        storage_reference=storage_reference,
        expires_at=expires_at,
    )
    session.add(asset)
    session.flush()
    return asset


def require_purpose(session, student_id, purpose):
    field = {"longitudinal": "longitudinal_tracking", "research": "research_data_use"}.get(purpose)
    if not field:
        raise ConsentDenied("Unknown processing purpose")
    receipt = current_consent(session, student_id)
    if not getattr(receipt, field):
        raise ConsentDenied(f"{purpose} use was declined")
    return receipt


def create_trend(session, *, student_id, **values):
    """Trusted worker service; DB evidence constraints additionally validate lineage."""
    from app.models import SentimentTrend

    receipt = require_purpose(session, student_id, "longitudinal")
    if "consent_record_id" in values:
        raise ValueError("The service selects current consent")
    row = SentimentTrend(student_id=student_id, consent_record_id=receipt.id, **values)
    session.add(row)
    session.flush()
    return row


def register_research_use(session, *, student_id, **values):
    """Consent is necessary but does not replace institutional ethics approval."""
    receipt = require_purpose(session, student_id, "research")
    inference = session.get(ModelInference, values.get("inference_id"))
    if (
        not inference
        or inference.student_id != student_id
        or inference.deleted_at
        or inference.processing_status != "completed"
    ):
        raise ValueError("Completed student-owned inference required")
    if not values.get("ethics_approval_reference") or not values.get("deidentification_version"):
        raise ValueError("Ethics approval and de-identification provenance required")
    if "consent_record_id" in values:
        raise ValueError("The service selects current consent")
    row = ResearchDatasetRecord(student_id=student_id, consent_record_id=receipt.id, **values)
    session.add(row)
    session.flush()
    return row
