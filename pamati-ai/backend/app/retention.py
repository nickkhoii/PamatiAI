"""Retention rules and transparent, finite institutional holds; no content access bypass."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.models import RetentionHold, SystemSetting, utcnow

Category = Literal["conversations", "analysis", "research", "consent_audit", "check_ins"]


class RetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = Field(default=1, ge=1)
    conversation_days: int = Field(default=180, ge=1, le=3650)
    analysis_days: int = Field(default=90, ge=1, le=3650)
    research_days: int = Field(default=365, ge=1, le=3650)
    consent_audit_days: int = Field(default=1825, ge=1, le=3650)
    raw_media_hours: int = Field(default=24, ge=1, le=168)
    backup_days: int = Field(default=90, ge=1, le=365)
    request_review_days: int = Field(default=30, ge=1, le=90)


def retention_policy(db, *, lock=False):
    # Shared locking reads are current under MySQL repeatable-read and avoid
    # extending availability using a cached, superseded retention policy.
    setting = db.get(SystemSetting, "data_retention",
                     with_for_update=True if lock else {"read": True}, populate_existing=True)
    return RetentionPolicy.model_validate(setting.value) if setting else RetentionPolicy()


def active_holds(db, student_id, category=None):
    query = select(RetentionHold).where(
        RetentionHold.student_id == student_id,
        RetentionHold.released_at.is_(None),
        RetentionHold.expires_at > utcnow(),
    )
    if category:
        query = query.where(RetentionHold.category == category)
    return list(db.scalars(query.order_by(RetentionHold.expires_at).with_for_update(read=True)
                           .execution_options(populate_existing=True)))


def deadline(db, student_id, category: Category, created_at: datetime, *, snapshot=None):
    current = retention_policy(db)
    saved = RetentionPolicy.model_validate(snapshot) if snapshot else current
    field = {
        "conversations": "conversation_days",
        "check_ins": "conversation_days",
        "analysis": "analysis_days",
        "research": "research_days",
        "consent_audit": "consent_audit_days",
    }[category]
    # An ordinary configuration increase cannot extend an already disclosed shorter period.
    due = created_at + timedelta(days=min(getattr(saved, field), getattr(current, field)))
    holds = active_holds(db, student_id, category)
    if holds:
        due = max(due, max(h.expires_at for h in holds))
    return due


def hold_view(row):
    return {
        "id": row.id,
        "category": row.category,
        "reason": row.reason,
        "legal_basis": row.legal_basis,
        "expires_at": row.expires_at,
        "created_at": row.created_at,
        "released_at": row.released_at,
    }


def retained(db, row, category: Category):
    """An expired record is unavailable even before a storage-erasure worker runs."""
    if row is None or getattr(row, "deleted_at", None):
        return False
    snapshot = getattr(row, "retention_snapshot", None)
    if category in {"analysis", "research"}:
        from app.models import ConsentRecord

        receipt = db.get(ConsentRecord, row.consent_record_id)
        snapshot = (receipt.disclosure_snapshot or {}).get("retention") if receipt else None
    if category == "analysis" and hasattr(row, "session_id"):
        from app.models import InteractionSession, Message

        interaction = db.get(InteractionSession, row.session_id, populate_existing=True)
        if not interaction or interaction.deleted_at or not retained(db, interaction.conversation, "conversations"):
            return False
        if row.message_id:
            message = db.get(Message, row.message_id, populate_existing=True)
            if not message or message.deleted_at:
                return False
    return deadline(db, row.student_id, category, row.created_at, snapshot=snapshot) > utcnow()
