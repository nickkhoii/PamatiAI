"""Normalized persistence entities. No diagnosis or raw media payload columns."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.db import Base

UTCDateTime = DateTime().with_variant(DATETIME(fsp=6), "mysql")
MODALITIES = ("text", "audio", "visual", "multimodal")


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


def identifier():
    return str(uuid4())


def choice(name, *values):
    return Enum(*values, name=name, native_enum=False, create_constraint=True)


def reference(target, **kwargs):
    return mapped_column(String(36), ForeignKey(target, ondelete="RESTRICT"), **kwargs)


def owned_link(local, remote):
    return ForeignKeyConstraint(local, remote, ondelete="RESTRICT")


class Entity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

    @declared_attr.directive
    def __table_args__(cls):
        return {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        }


TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


class Mutable:
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class SoftDelete:
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)


class User(Entity, Mutable, SoftDelete, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    is_development_account: Mapped[bool] = mapped_column(Boolean, default=False)
    roles: Mapped[list["Role"]] = relationship(secondary="user_roles", back_populates="users")
    student_profile: Mapped["StudentProfile | None"] = relationship(back_populates="user")
    reviewer_profile: Mapped["ReviewerProfile | None"] = relationship(back_populates="user")


class Role(Entity, Base):
    __tablename__ = "roles"
    code: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(String(255))
    users: Mapped[list[User]] = relationship(secondary="user_roles", back_populates="roles")
    permissions: Mapped[list["Permission"]] = relationship(secondary="role_permissions")


class Permission(Entity, Base):
    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(String(255))


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = TABLE_OPTIONS
    user_id: Mapped[str] = reference("users.id", primary_key=True)
    role_id: Mapped[str] = reference("roles.id", primary_key=True, index=True)
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = TABLE_OPTIONS
    role_id: Mapped[str] = reference("roles.id", primary_key=True)
    permission_id: Mapped[str] = reference("permissions.id", primary_key=True, index=True)


class StudentProfile(Mutable, SoftDelete, Base):
    __tablename__ = "student_profiles"
    __table_args__ = TABLE_OPTIONS
    user_id: Mapped[str] = reference("users.id", primary_key=True)
    research_pseudonym: Mapped[str] = mapped_column(String(36), default=identifier, unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    user: Mapped[User] = relationship(back_populates="student_profile")
    consents: Mapped[list["ConsentRecord"]] = relationship(back_populates="student")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="student")


class ReviewerProfile(Mutable, SoftDelete, Base):
    __tablename__ = "reviewer_profiles"
    __table_args__ = TABLE_OPTIONS
    user_id: Mapped[str] = reference("users.id", primary_key=True)
    professional_title: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    user: Mapped[User] = relationship(back_populates="reviewer_profile")


class ReviewerAssignment(Entity, Base):
    __tablename__ = "reviewer_assignments"
    __table_args__ = (UniqueConstraint("student_id", "reviewer_id"), TABLE_OPTIONS)
    student_id: Mapped[str] = reference("student_profiles.user_id", index=True)
    reviewer_id: Mapped[str] = reference("reviewer_profiles.user_id", index=True)
    assigned_by: Mapped[str] = reference("users.id")
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ConsentRecord(Entity, Base):
    __tablename__ = "consent_records"
    __table_args__ = (
        UniqueConstraint("student_id", "version"),
        UniqueConstraint("id", "student_id"),
        CheckConstraint("version > 0", name="positive_version"),
        CheckConstraint("NOT retain_audio OR audio_processing", name="audio_retention_consent"),
        CheckConstraint("NOT retain_visual OR visual_processing", name="visual_retention_consent"),
        CheckConstraint(
            "withdrawn_at IS NULL OR withdrawn_at >= created_at", name="withdrawal_time"
        ),
        TABLE_OPTIONS,
    )
    student_id: Mapped[str] = reference("student_profiles.user_id", index=True)
    version: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[str] = mapped_column(String(80))
    disclosure_snapshot: Mapped[dict | None] = mapped_column(JSON)
    text_processing: Mapped[bool] = mapped_column(Boolean, default=False)
    audio_processing: Mapped[bool] = mapped_column(Boolean, default=False)
    visual_processing: Mapped[bool] = mapped_column(Boolean, default=False)
    longitudinal_tracking: Mapped[bool] = mapped_column(Boolean, default=False)
    research_data_use: Mapped[bool] = mapped_column(Boolean, default=False)
    retain_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    retain_visual: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewer_access: Mapped[bool] = mapped_column(Boolean, default=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    student: Mapped[StudentProfile] = relationship(back_populates="consents")


class Conversation(Entity, Mutable, SoftDelete, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("id", "student_id"),
        Index("ix_conversations_student_created", "student_id", "created_at"),
        TABLE_OPTIONS,
    )
    student_id: Mapped[str] = reference("student_profiles.user_id")
    retention_snapshot: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        choice("conversation_status", "open", "closed"), default="open"
    )
    student: Mapped[StudentProfile] = relationship(back_populates="conversations")
    sessions: Mapped[list["InteractionSession"]] = relationship(back_populates="conversation")


class InteractionSession(Entity, Mutable, SoftDelete, Base):
    __tablename__ = "interaction_sessions"
    __table_args__ = (
        UniqueConstraint("id", "student_id"),
        owned_link(
            ["conversation_id", "student_id"], ["conversations.id", "conversations.student_id"]
        ),
        CheckConstraint("ended_at IS NULL OR ended_at >= created_at", name="session_time"),
        TABLE_OPTIONS,
    )
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    student_id: Mapped[str] = reference("student_profiles.user_id", index=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    conversation: Mapped[Conversation] = relationship(
        back_populates="sessions", foreign_keys=[conversation_id]
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", foreign_keys="Message.session_id"
    )


class Message(Entity, SoftDelete, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("id", "session_id", "student_id"),
        UniqueConstraint("session_id", "sequence_number"),
        owned_link(
            ["session_id", "student_id"],
            ["interaction_sessions.id", "interaction_sessions.student_id"],
        ),
        CheckConstraint("sequence_number >= 0", name="message_sequence"),
        TABLE_OPTIONS,
    )
    session_id: Mapped[str] = mapped_column(String(36))
    student_id: Mapped[str] = reference("student_profiles.user_id", index=True)
    sender: Mapped[str] = mapped_column(choice("message_sender", "student", "assistant", "system"))
    sequence_number: Mapped[int] = mapped_column(Integer)
    text_content: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    generation: Mapped[dict | None] = mapped_column(JSON)
    session: Mapped[InteractionSession] = relationship(
        back_populates="messages", foreign_keys=[session_id]
    )


class ModelVersion(Entity, Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("model_identifier", "version", "modality"),
        UniqueConstraint("id", "modality"),
        TABLE_OPTIONS,
    )
    model_identifier: Mapped[str] = mapped_column(String(180))
    version: Mapped[str] = mapped_column(String(120))
    modality: Mapped[str] = mapped_column(choice("model_modality", *MODALITIES))
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    license: Mapped[str | None] = mapped_column(String(120))
    model_card_reference: Mapped[str | None] = mapped_column(String(500))
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    inferences: Mapped[list["ModelInference"]] = relationship(
        back_populates="model", foreign_keys="ModelInference.model_version_id"
    )


class ModelInference(Entity, Mutable, SoftDelete, Base):
    __tablename__ = "model_inferences"
    __table_args__ = (
        UniqueConstraint("id", "student_id"),
        UniqueConstraint("id", "modality"),
        owned_link(
            ["model_version_id", "modality"], ["model_versions.id", "model_versions.modality"]
        ),
        owned_link(
            ["session_id", "student_id"],
            ["interaction_sessions.id", "interaction_sessions.student_id"],
        ),
        owned_link(
            ["message_id", "session_id", "student_id"],
            ["messages.id", "messages.session_id", "messages.student_id"],
        ),
        owned_link(
            ["consent_record_id", "student_id"],
            ["consent_records.id", "consent_records.student_id"],
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"
        ),
        CheckConstraint(
            "completed_at IS NULL OR (started_at IS NOT NULL AND completed_at >= started_at)",
            name="inference_time",
        ),
        CheckConstraint("started_at IS NULL OR started_at >= created_at", name="start_time"),
        CheckConstraint(
            "processing_status <> 'running' OR started_at IS NOT NULL", name="running_time"
        ),
        CheckConstraint(
            "processing_status NOT IN ('completed', 'abstained') OR completed_at IS NOT NULL",
            name="completion_time",
        ),
        Index("ix_inferences_student_created", "student_id", "created_at"),
        Index("ix_inferences_status_created", "processing_status", "created_at"),
        TABLE_OPTIONS,
    )
    student_id: Mapped[str] = reference("student_profiles.user_id")
    session_id: Mapped[str] = mapped_column(String(36))
    message_id: Mapped[str | None] = mapped_column(String(36), index=True)
    consent_record_id: Mapped[str] = mapped_column(String(36), index=True)
    model_version_id: Mapped[str] = mapped_column(String(36), index=True)
    modality: Mapped[str] = mapped_column(choice("inference_modality", *MODALITIES))
    input_modalities: Mapped[list | None] = mapped_column(JSON)
    processing_status: Mapped[str] = mapped_column(
        choice(
            "processing_status",
            "pending",
            "running",
            "completed",
            "failed",
            "cancelled",
            "abstained",
        ),
        default="pending",
    )
    preprocessing_version: Mapped[str] = mapped_column(String(120))
    adapter_version: Mapped[str] = mapped_column(String(120))
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    confidence: Mapped[float | None] = mapped_column(Float)
    uncertainty: Mapped[dict | None] = mapped_column(JSON)
    uncertainty_method: Mapped[str | None] = mapped_column(String(120))
    error_code: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[ModelVersion] = relationship(
        back_populates="inferences", foreign_keys=[model_version_id]
    )
    consent: Mapped[ConsentRecord] = relationship(foreign_keys=[consent_record_id])


class Analysis:
    inference_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    modality: Mapped[str] = mapped_column(String(16))
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    @declared_attr
    def inference(cls):
        return relationship(ModelInference, foreign_keys=[cls.inference_id])


def analysis_constraints(modality):
    return (
        owned_link(
            ["inference_id", "modality"], ["model_inferences.id", "model_inferences.modality"]
        ),
        CheckConstraint(f"modality = '{modality}'", name="analysis_modality"),
        TABLE_OPTIONS,
    )


class TextAnalysis(Analysis, Base):
    __tablename__ = "text_analyses"
    __table_args__ = analysis_constraints("text")
    language: Mapped[str | None] = mapped_column(String(35))


class AudioAnalysis(Analysis, Base):
    __tablename__ = "audio_analyses"
    __table_args__ = (
        *analysis_constraints("audio")[:-1],
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="audio_duration"),
        TABLE_OPTIONS,
    )
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    # Deliberately no transcript/raw waveform duplication.


class VisualAnalysis(Analysis, Base):
    __tablename__ = "visual_analyses"
    __table_args__ = (
        *analysis_constraints("visual")[:-1],
        CheckConstraint(
            "sampled_frame_count IS NULL OR sampled_frame_count >= 0", name="frame_count"
        ),
        TABLE_OPTIONS,
    )
    sampled_frame_count: Mapped[int | None] = mapped_column(Integer)


class MultimodalAnalysis(Analysis, Base):
    __tablename__ = "multimodal_analyses"
    __table_args__ = analysis_constraints("multimodal")
    fusion_strategy_version: Mapped[str] = mapped_column(String(120))
    missing_modalities: Mapped[list] = mapped_column(JSON, default=list)


class FusionInput(Base):
    __tablename__ = "fusion_inputs"
    __table_args__ = (
        owned_link(
            ["fusion_inference_id", "student_id"],
            ["model_inferences.id", "model_inferences.student_id"],
        ),
        owned_link(
            ["source_inference_id", "student_id"],
            ["model_inferences.id", "model_inferences.student_id"],
        ),
        CheckConstraint("fusion_inference_id <> source_inference_id", name="no_self_fusion"),
        TABLE_OPTIONS,
    )
    fusion_inference_id: Mapped[str] = reference(
        "multimodal_analyses.inference_id", primary_key=True
    )
    source_inference_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    student_id: Mapped[str] = reference("student_profiles.user_id")


class SentimentObservation(Entity, SoftDelete, Base):
    __tablename__ = "sentiment_observations"
    __table_args__ = (
        UniqueConstraint("id", "student_id"),
        UniqueConstraint("inference_id", "dimension"),
        owned_link(
            ["inference_id", "student_id"], ["model_inferences.id", "model_inferences.student_id"]
        ),
        CheckConstraint("score >= -1 AND score <= 1", name="sentiment_range"),
        Index("ix_observations_student_time", "student_id", "observed_at"),
        TABLE_OPTIONS,
    )
    student_id: Mapped[str] = reference("student_profiles.user_id")
    inference_id: Mapped[str] = mapped_column(String(36))
    dimension: Mapped[str] = mapped_column(String(60))
    score: Mapped[float] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime)
    inference: Mapped[ModelInference] = relationship(foreign_keys=[inference_id])


class SentimentTrend(Entity, SoftDelete, Base):
    __tablename__ = "sentiment_trends"
    __table_args__ = (
        UniqueConstraint("id", "student_id"),
        owned_link(
            ["consent_record_id", "student_id"],
            ["consent_records.id", "consent_records.student_id"],
        ),
        CheckConstraint("window_end > window_start", name="trend_window"),
        CheckConstraint("sample_count > 0", name="trend_sample_count"),
        Index("ix_trends_student_window", "student_id", "window_start", "window_end"),
        TABLE_OPTIONS,
    )
    student_id: Mapped[str] = reference("student_profiles.user_id")
    consent_record_id: Mapped[str] = mapped_column(String(36))
    model_version_id: Mapped[str] = reference("model_versions.id")
    dimension: Mapped[str] = mapped_column(String(60))
    window_start: Mapped[datetime] = mapped_column(UTCDateTime)
    window_end: Mapped[datetime] = mapped_column(UTCDateTime)
    algorithm_version: Mapped[str] = mapped_column(String(120))
    sample_count: Mapped[int] = mapped_column(Integer)
    summary: Mapped[dict] = mapped_column(JSON)


class TrendObservation(Base):
    __tablename__ = "trend_observations"
    __table_args__ = (
        owned_link(
            ["trend_id", "student_id"], ["sentiment_trends.id", "sentiment_trends.student_id"]
        ),
        owned_link(
            ["observation_id", "student_id"],
            ["sentiment_observations.id", "sentiment_observations.student_id"],
        ),
        TABLE_OPTIONS,
    )
    trend_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    observation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    student_id: Mapped[str] = reference("student_profiles.user_id")


class RiskSignal(Entity, Mutable, SoftDelete, Base):
    __tablename__ = "risk_signals"
    __table_args__ = (
        UniqueConstraint("id", "student_id"),
        owned_link(
            ["inference_id", "student_id"], ["model_inferences.id", "model_inferences.student_id"]
        ),
        owned_link(
            ["trend_id", "student_id"], ["sentiment_trends.id", "sentiment_trends.student_id"]
        ),
        CheckConstraint("inference_id IS NOT NULL OR trend_id IS NOT NULL", name="signal_source"),
        Index("ix_risks_student_status", "student_id", "status"),
        TABLE_OPTIONS,
    )
    student_id: Mapped[str] = reference("student_profiles.user_id")
    inference_id: Mapped[str | None] = mapped_column(String(36))
    trend_id: Mapped[str | None] = mapped_column(String(36))
    signal_code: Mapped[str] = mapped_column(String(80))
    priority: Mapped[str] = mapped_column(choice("signal_priority", "routine", "prompt", "urgent"))
    status: Mapped[str] = mapped_column(
        choice("signal_status", "pending_review", "acknowledged", "resolved", "dismissed"),
        default="pending_review",
    )
    explanation: Mapped[dict] = mapped_column(JSON)
    rule_version: Mapped[str] = mapped_column(String(120))


class HumanReview(Entity, Base):
    __tablename__ = "human_reviews"
    __table_args__ = (
        UniqueConstraint("id", "student_id"),
        owned_link(
            ["risk_signal_id", "student_id"], ["risk_signals.id", "risk_signals.student_id"]
        ),
        TABLE_OPTIONS,
    )
    student_id: Mapped[str] = reference("student_profiles.user_id")
    risk_signal_id: Mapped[str] = mapped_column(String(36), index=True)
    reviewer_id: Mapped[str] = reference("reviewer_profiles.user_id", index=True)
    decision: Mapped[str] = mapped_column(
        choice("review_decision", "acknowledge", "dismiss", "follow_up", "refer")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    risk_signal: Mapped[RiskSignal] = relationship(foreign_keys=[risk_signal_id])


class ReferralRecord(Entity, Mutable, SoftDelete, Base):
    __tablename__ = "referral_records"
    __table_args__ = (
        owned_link(
            ["human_review_id", "student_id"], ["human_reviews.id", "human_reviews.student_id"]
        ),
        TABLE_OPTIONS,
    )
    student_id: Mapped[str] = reference("student_profiles.user_id", index=True)
    human_review_id: Mapped[str] = mapped_column(String(36), index=True)
    service_reference: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        choice("referral_status", "offered", "accepted", "declined", "closed"), default="offered"
    )
    student_decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Notification(Entity, Mutable, SoftDelete, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="notification_attempts"),
        Index("ix_notifications_dispatch", "status", "scheduled_at"),
        TABLE_OPTIONS,
    )
    recipient_id: Mapped[str] = reference("users.id", index=True)
    deduplication_key: Mapped[str] = mapped_column(String(120), unique=True)
    channel: Mapped[str] = mapped_column(choice("notification_channel", "in_app", "email"))
    template_code: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(
        choice("notification_status", "pending", "sent", "failed", "cancelled"), default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # No message content, risk narrative or media in notification payloads.


class AuditLog(Entity, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audits_actor_time", "actor_id", "created_at"),
        Index("ix_audits_resource_time", "resource_type", "resource_id", "created_at"),
        TABLE_OPTIONS,
    )
    actor_id: Mapped[str | None] = reference("users.id")
    action: Mapped[str] = mapped_column(String(80))
    resource_type: Mapped[str] = mapped_column(String(60))
    resource_id: Mapped[str | None] = mapped_column(String(36))
    outcome: Mapped[str] = mapped_column(choice("audit_outcome", "success", "denied", "failure"))
    request_id: Mapped[str | None] = mapped_column(String(36), index=True)


class ResearchDatasetRecord(Entity, SoftDelete, Base):
    __tablename__ = "research_dataset_records"
    __table_args__ = (
        UniqueConstraint("dataset_identifier", "dataset_version", "inference_id"),
        owned_link(
            ["inference_id", "student_id"], ["model_inferences.id", "model_inferences.student_id"]
        ),
        owned_link(
            ["consent_record_id", "student_id"],
            ["consent_records.id", "consent_records.student_id"],
        ),
        TABLE_OPTIONS,
    )
    student_id: Mapped[str] = reference("student_profiles.user_id", index=True)
    inference_id: Mapped[str] = mapped_column(String(36))
    consent_record_id: Mapped[str] = mapped_column(String(36))
    dataset_identifier: Mapped[str] = mapped_column(String(120))
    dataset_version: Mapped[str] = mapped_column(String(80))
    ethics_approval_reference: Mapped[str] = mapped_column(String(120))
    deidentification_version: Mapped[str] = mapped_column(String(120))
    split: Mapped[str] = mapped_column(choice("dataset_split", "train", "validation", "test"))
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class SystemSetting(Mutable, Base):
    __tablename__ = "system_settings"
    __table_args__ = TABLE_OPTIONS
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(String(255))
    updated_by: Mapped[str | None] = reference("users.id")
    # Configuration only; never passwords, signing keys or connection strings.


class MediaAsset(Entity, SoftDelete, Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        owned_link(
            ["session_id", "student_id"],
            ["interaction_sessions.id", "interaction_sessions.student_id"],
        ),
        owned_link(
            ["consent_record_id", "student_id"],
            ["consent_records.id", "consent_records.student_id"],
        ),
        CheckConstraint("expires_at > created_at", name="media_expiry"),
        TABLE_OPTIONS,
    )
    student_id: Mapped[str] = reference("student_profiles.user_id", index=True)
    session_id: Mapped[str] = mapped_column(String(36))
    consent_record_id: Mapped[str] = mapped_column(String(36))
    modality: Mapped[str] = mapped_column(choice("media_modality", "audio", "visual"))
    storage_reference: Mapped[str] = mapped_column(String(255), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    purged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AuthSession(Entity, Base):
    __tablename__ = "auth_sessions"
    user_id: Mapped[str] = reference("users.id", index=True)
    family_id: Mapped[str] = mapped_column(String(36), index=True)
    access_hash: Mapped[str] = mapped_column(String(64), unique=True)
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True)
    access_expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AuthChallenge(Entity, Base):
    __tablename__ = "auth_challenges"
    user_id: Mapped[str | None] = reference("users.id", index=True)
    email: Mapped[str] = mapped_column(String(254))
    purpose: Mapped[str] = mapped_column(String(16))
    role_code: Mapped[str | None] = mapped_column(String(40))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AuthDelivery(Entity, Base):
    __tablename__ = "auth_deliveries"
    challenge_id: Mapped[str] = reference("auth_challenges.id", index=True)
    encrypted_payload: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"
    __table_args__ = TABLE_OPTIONS
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(UTCDateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class SupportRequest(Entity, Base):
    __tablename__ = "support_requests"
    student_id: Mapped[str] = reference("student_profiles.user_id", index=True)
    status: Mapped[str] = mapped_column(String(20), default="requested")


class DataControlRequest(Entity, Base):
    __tablename__ = "data_control_requests"
    student_id: Mapped[str] = reference("student_profiles.user_id", index=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="requested")
    review_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    decision_reason: Mapped[str | None] = mapped_column(String(500))
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class RetentionHold(Entity, Base):
    __tablename__ = "retention_holds"
    student_id: Mapped[str] = reference("student_profiles.user_id", index=True)
    category: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(500))
    legal_basis: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_by: Mapped[str] = reference("users.id")
    released_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
