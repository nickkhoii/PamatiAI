"""MySQL guards for immutable provenance, audit integrity and consented writes."""

from alembic import op

revision = "0003_persistence_guards"
down_revision = "0002_research_schema"
branch_labels = None
depends_on = None

CONSENT_CHECK = """
    IF NOT EXISTS (
        SELECT 1 FROM consent_records c
        JOIN student_profiles s ON s.user_id = c.student_id
        JOIN users u ON u.id = s.user_id
        WHERE c.id = NEW.consent_record_id AND c.student_id = NEW.student_id
        AND c.withdrawn_at IS NULL AND s.deleted_at IS NULL
        AND u.deleted_at IS NULL AND u.is_active = 1
        AND c.version = (SELECT MAX(latest.version) FROM consent_records latest
                         WHERE latest.student_id = NEW.student_id)
        AND ((NEW.modality = 'text' AND c.text_processing = 1)
          OR (NEW.modality = 'audio' AND c.audio_processing = 1)
          OR (NEW.modality = 'visual' AND c.visual_processing = 1)
          OR (NEW.modality = 'multimodal' AND
              (c.text_processing = 1 OR c.audio_processing = 1 OR c.visual_processing = 1)))
    ) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Active modality consent required'; END IF;
"""


def upgrade():
    op.execute(
        """CREATE TRIGGER inference_insert_consent BEFORE INSERT ON model_inferences
                  FOR EACH ROW BEGIN """
        + CONSENT_CHECK
        + " END"
    )
    op.execute(
        """CREATE TRIGGER inference_update_guard BEFORE UPDATE ON model_inferences
        FOR EACH ROW BEGIN
        IF NOT (NEW.id <=> OLD.id) OR NOT (NEW.student_id <=> OLD.student_id)
           OR NOT (NEW.session_id <=> OLD.session_id)
           OR NOT (NEW.message_id <=> OLD.message_id)
           OR NOT (NEW.model_version_id <=> OLD.model_version_id)
           OR NOT (NEW.modality <=> OLD.modality)
           OR NOT (NEW.consent_record_id <=> OLD.consent_record_id)
           OR NOT (NEW.adapter_version <=> OLD.adapter_version)
           OR NOT (NEW.preprocessing_version <=> OLD.preprocessing_version)
           OR NOT (NEW.created_at <=> OLD.created_at)
        THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Inference provenance is immutable'; END IF;
        IF NEW.processing_status IN ('running', 'completed', 'abstained')
           AND (NOT (NEW.processing_status <=> OLD.processing_status)
                OR NOT (NEW.confidence <=> OLD.confidence)
                OR NOT (NEW.uncertainty <=> OLD.uncertainty)) THEN
        """
        + CONSENT_CHECK
        + " END IF; END"
    )
    op.execute("""CREATE TRIGGER consent_update_guard BEFORE UPDATE ON consent_records
        FOR EACH ROW BEGIN
        IF NEW.id <> OLD.id OR NOT (NEW.student_id <=> OLD.student_id) OR NEW.version <> OLD.version
           OR NEW.policy_version <> OLD.policy_version OR NEW.created_at <> OLD.created_at
           OR NEW.text_processing <> OLD.text_processing OR NEW.audio_processing <> OLD.audio_processing
           OR NEW.visual_processing <> OLD.visual_processing
           OR NEW.longitudinal_tracking <> OLD.longitudinal_tracking
           OR NEW.research_data_use <> OLD.research_data_use
           OR NEW.retain_audio <> OLD.retain_audio OR NEW.retain_visual <> OLD.retain_visual
           OR NEW.reviewer_access <> OLD.reviewer_access
           OR (OLD.withdrawn_at IS NOT NULL AND NOT (NEW.withdrawn_at <=> OLD.withdrawn_at))
        THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Consent receipts are immutable; append a new version'; END IF;
        END""")
    op.execute("""CREATE TRIGGER model_version_update_guard BEFORE UPDATE ON model_versions
        FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Model versions are immutable'""")
    op.execute("""CREATE TRIGGER consent_no_delete BEFORE DELETE ON consent_records
        FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Consent history cannot be deleted by runtime writes'""")
    for event in ("UPDATE", "DELETE"):
        op.execute(f"""CREATE TRIGGER audit_no_{event.lower()} BEFORE {event} ON audit_logs
            FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Audit log is append-only'""")
    op.execute("""CREATE TRIGGER media_insert_consent BEFORE INSERT ON media_assets
        FOR EACH ROW BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM consent_records c
            WHERE c.id = NEW.consent_record_id AND c.student_id = NEW.student_id
            AND c.withdrawn_at IS NULL
            AND c.version = (SELECT MAX(latest.version) FROM consent_records latest
                             WHERE latest.student_id = NEW.student_id)
            AND ((NEW.modality = 'audio' AND c.audio_processing = 1 AND c.retain_audio = 1)
              OR (NEW.modality = 'visual' AND c.visual_processing = 1 AND c.retain_visual = 1))
        ) OR NOT EXISTS (
            SELECT 1 FROM system_settings s WHERE s.`key` = 'raw_media_retention'
            AND JSON_EXTRACT(s.value, '$.enabled') = CAST('true' AS JSON)
        ) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Media retention configuration and consent required'; END IF;
        END""")
    op.execute("""CREATE TRIGGER research_insert_consent BEFORE INSERT ON research_dataset_records
        FOR EACH ROW BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM consent_records c WHERE c.id = NEW.consent_record_id
            AND c.student_id = NEW.student_id AND c.research_data_use = 1
            AND c.withdrawn_at IS NULL
            AND c.version = (SELECT MAX(latest.version) FROM consent_records latest
                             WHERE latest.student_id = NEW.student_id)
        ) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Research consent required'; END IF;
        END""")
    op.execute("""CREATE TRIGGER trend_insert_consent BEFORE INSERT ON sentiment_trends
        FOR EACH ROW BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM consent_records c WHERE c.id = NEW.consent_record_id
            AND c.student_id = NEW.student_id AND c.longitudinal_tracking = 1
            AND c.withdrawn_at IS NULL
            AND c.version = (SELECT MAX(latest.version) FROM consent_records latest
                             WHERE latest.student_id = NEW.student_id)
        ) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Longitudinal consent required'; END IF;
        END""")


def downgrade():
    for name in (
        "trend_insert_consent",
        "research_insert_consent",
        "media_insert_consent",
        "audit_no_delete",
        "audit_no_update",
        "model_version_update_guard",
        "consent_no_delete",
        "consent_update_guard",
        "inference_update_guard",
        "inference_insert_consent",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
