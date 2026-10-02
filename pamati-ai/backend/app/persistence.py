"""Transactional consent-aware writes; callers still need authenticated RBAC checks."""

from datetime import datetime

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
    utcnow,
)

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
    student = session.scalar(
        select(StudentProfile)
        .where(StudentProfile.user_id == student_id, StudentProfile.deleted_at.is_(None))
        .with_for_update()
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
    )
    if receipt is None or receipt.withdrawn_at is not None:
        raise ConsentDenied("Active consent is required")
    return receipt


def record_consent(session: Session, student_id: str, policy_version: str, **permissions):
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
    )
    receipt = ConsentRecord(
        student_id=student_id,
        version=previous.version + 1 if previous else 1,
        policy_version=policy_version,
        **permissions,
    )
    session.add(receipt)
    session.flush()
    return receipt


def withdraw_consent(session: Session, student_id: str):
    receipt = current_consent(session, student_id)
    receipt.withdrawn_at = utcnow()
    pending = session.scalars(
        select(ModelInference).where(
            ModelInference.student_id == student_id,
            ModelInference.processing_status.in_(["pending", "running"]),
        )
    ).all()
    for inference in pending:
        inference.processing_status = "cancelled"
    for record in session.scalars(
        select(ResearchDatasetRecord).where(
            ResearchDatasetRecord.student_id == student_id,
            ResearchDatasetRecord.revoked_at.is_(None),
        )
    ):
        record.revoked_at = receipt.withdrawn_at
    session.flush()
    # Physical object-store purge and already exported dataset revocation need future workers.


def create_inference(
    session: Session,
    *,
    student_id: str,
    session_id: str,
    model_version_id: str,
    preprocessing_version: str,
    adapter_version: str,
    message_id: str | None = None,
):
    receipt = current_consent(session, student_id)
    interaction = session.get(InteractionSession, session_id)
    model = session.get(ModelVersion, model_version_id)
    if interaction is None or interaction.student_id != student_id or interaction.deleted_at:
        raise ValueError("Interaction session does not belong to active student")
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
    inference = ModelInference(
        student_id=student_id,
        session_id=session_id,
        message_id=message_id,
        consent_record_id=receipt.id,
        model_version_id=model.id,
        modality=model.modality,
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
