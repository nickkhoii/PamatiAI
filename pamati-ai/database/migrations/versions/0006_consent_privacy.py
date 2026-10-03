"""Consent disclosure evidence, processing manifests and institutional retention holds."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "0006_consent_privacy"
down_revision = "0005_authentication"
branch_labels = None
depends_on = None
DT = sa.DateTime().with_variant(DATETIME(fsp=6), "mysql")


def upgrade():
    op.add_column("consent_records", sa.Column("disclosure_snapshot", sa.JSON(), nullable=True))
    op.add_column("conversations", sa.Column("retention_snapshot", sa.JSON(), nullable=True))
    op.add_column("model_inferences", sa.Column("input_modalities", sa.JSON(), nullable=True))
    op.add_column("data_control_requests", sa.Column("review_due_at", DT, nullable=True))
    op.add_column(
        "data_control_requests",
        sa.Column("decision_reason", sa.String(500), nullable=True),
    )
    op.add_column("data_control_requests", sa.Column("decided_at", DT, nullable=True))
    op.create_table(
        "retention_holds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", DT, nullable=False),
        sa.Column(
            "student_id",
            sa.String(36),
            sa.ForeignKey("student_profiles.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("legal_basis", sa.String(255), nullable=False),
        sa.Column("expires_at", DT, nullable=False),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("released_at", DT),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )
    op.create_index("ix_retention_holds_student_id", "retention_holds", ["student_id"])
    op.execute(
        "UPDATE model_inferences SET processing_status = 'cancelled' "
        "WHERE processing_status IN ('pending', 'running')"
    )
    op.execute(
        "INSERT INTO system_settings (`key`, value, description, updated_at) "
        "SELECT 'data_retention', JSON_OBJECT('version',1,'conversation_days',180,"
        "'analysis_days',90,'research_days',365,'consent_audit_days',1825,"
        "'raw_media_hours',24,'backup_days',90,'request_review_days',30), "
        "'Configured retention limits', CURRENT_TIMESTAMP WHERE NOT EXISTS "
        "(SELECT 1 FROM system_settings WHERE `key` = 'data_retention')"
    )
    for table, column, name in [
        ("consent_records", "disclosure_snapshot", "consent_disclosure_immutable"),
        ("conversations", "retention_snapshot", "conversation_retention_immutable"),
        ("model_inferences", "input_modalities", "inference_manifest_immutable"),
    ]:
        op.execute(f"""CREATE TRIGGER {name} BEFORE UPDATE ON {table} FOR EACH ROW
            BEGIN IF NOT (NEW.{column} <=> OLD.{column}) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Consent and processing evidence is immutable';
            END IF; END""")
    op.execute("""CREATE TRIGGER inference_manifest_consent BEFORE INSERT ON model_inferences
        FOR EACH ROW BEGIN
        IF NEW.input_modalities IS NOT NULL THEN
        IF JSON_TYPE(NEW.input_modalities) <> 'ARRAY' OR JSON_LENGTH(NEW.input_modalities) = 0
            OR JSON_LENGTH(NEW.input_modalities) > 3
            OR EXISTS (SELECT 1 FROM JSON_TABLE(NEW.input_modalities, '$[*]'
                COLUMNS (modality VARCHAR(16) PATH '$')) inputs
                JOIN consent_records c ON c.id = NEW.consent_record_id
                WHERE inputs.modality NOT IN ('text','audio','visual')
                OR (inputs.modality = 'text' AND c.text_processing = 0)
                OR (inputs.modality = 'audio' AND c.audio_processing = 0)
                OR (inputs.modality = 'visual' AND c.visual_processing = 0))
            OR (NEW.modality <> 'multimodal' AND
                (JSON_LENGTH(NEW.input_modalities) <> 1 OR
                 JSON_UNQUOTE(JSON_EXTRACT(NEW.input_modalities, '$[0]')) <> NEW.modality))
        THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Input manifest requires modality consent';
        END IF; END IF; END""")


def downgrade():
    for name in [
        "inference_manifest_consent",
        "inference_manifest_immutable",
        "conversation_retention_immutable",
        "consent_disclosure_immutable",
    ]:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_table("retention_holds")
    for table, columns in [
        ("data_control_requests", ["decided_at", "decision_reason", "review_due_at"]),
        ("model_inferences", ["input_modalities"]),
        ("conversations", ["retention_snapshot"]),
        ("consent_records", ["disclosure_snapshot"]),
    ]:
        for column in columns:
            op.drop_column(table, column)
