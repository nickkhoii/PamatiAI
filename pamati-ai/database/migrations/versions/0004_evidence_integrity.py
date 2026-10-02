"""Validate inference lifecycle, evidence lineage and reviewer access at write time."""

from alembic import op

revision = "0004_evidence_integrity"
down_revision = "0003_persistence_guards"
branch_labels = None
depends_on = None

CHECKS = [
    (
        "model_inferences",
        "ck_model_inferences_start_time",
        "started_at IS NULL OR started_at >= created_at",
    ),
    (
        "model_inferences",
        "ck_model_inferences_running_time",
        "processing_status <> 'running' OR started_at IS NOT NULL",
    ),
    (
        "model_inferences",
        "ck_model_inferences_completion_time",
        "processing_status NOT IN ('completed', 'abstained') OR completed_at IS NOT NULL",
    ),
    (
        "audio_analyses",
        "ck_audio_analyses_audio_duration",
        "duration_seconds IS NULL OR duration_seconds >= 0",
    ),
    (
        "visual_analyses",
        "ck_visual_analyses_frame_count",
        "sampled_frame_count IS NULL OR sampled_frame_count >= 0",
    ),
]

IMMUTABLE_COLUMNS = {
    "research_dataset_records": [
        "id",
        "student_id",
        "inference_id",
        "consent_record_id",
        "dataset_identifier",
        "dataset_version",
        "split",
        "ethics_approval_reference",
        "deidentification_version",
        "created_at",
    ],
    "fusion_inputs": ["fusion_inference_id", "source_inference_id", "student_id"],
    "trend_observations": ["trend_id", "observation_id", "student_id"],
}


def upgrade():
    for table, name, condition in CHECKS:
        op.create_check_constraint(op.f(name), table, condition)
    for table, columns in IMMUTABLE_COLUMNS.items():
        changes = " OR ".join(f"NOT (NEW.`{column}` <=> OLD.`{column}`)" for column in columns)
        op.execute(f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE ON {table}
            FOR EACH ROW BEGIN IF {changes} THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Evidence provenance is immutable'; END IF; END""")
    op.execute("""CREATE TRIGGER inference_terminal_guard BEFORE UPDATE ON model_inferences
        FOR EACH ROW BEGIN
        IF OLD.processing_status IN ('completed', 'failed', 'cancelled', 'abstained')
           AND (NEW.processing_status <> OLD.processing_status
                OR NOT (NEW.started_at <=> OLD.started_at)
                OR NOT (NEW.completed_at <=> OLD.completed_at)
                OR NOT (NEW.confidence <=> OLD.confidence)
                OR NOT (NEW.uncertainty <=> OLD.uncertainty)
                OR NOT (NEW.uncertainty_method <=> OLD.uncertainty_method)
                OR NOT (NEW.error_code <=> OLD.error_code))
        THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Terminal inference is immutable; create a new run'; END IF;
        END""")
    op.execute("""CREATE TRIGGER media_update_guard BEFORE UPDATE ON media_assets
        FOR EACH ROW BEGIN
        IF NEW.student_id <> OLD.student_id OR NEW.session_id <> OLD.session_id
           OR NEW.consent_record_id <> OLD.consent_record_id OR NEW.modality <> OLD.modality
           OR NEW.storage_reference <> OLD.storage_reference OR NEW.created_at <> OLD.created_at
           OR NEW.expires_at > OLD.expires_at
        THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Media provenance immutable; retention cannot be extended'; END IF;
        END""")
    op.execute("""CREATE TRIGGER observation_insert_guard BEFORE INSERT ON sentiment_observations
        FOR EACH ROW BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM model_inferences i JOIN consent_records c ON c.student_id = i.student_id
            WHERE i.id = NEW.inference_id AND i.student_id = NEW.student_id
            AND i.processing_status = 'completed' AND i.deleted_at IS NULL
            AND c.version = (SELECT MAX(v.version) FROM consent_records v WHERE v.student_id = NEW.student_id)
            AND c.withdrawn_at IS NULL AND c.longitudinal_tracking = 1
        ) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Completed inference and longitudinal consent required'; END IF;
        END""")
    op.execute("""CREATE TRIGGER trend_evidence_guard BEFORE INSERT ON trend_observations
        FOR EACH ROW BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM sentiment_trends t JOIN sentiment_observations o ON o.id = NEW.observation_id
            JOIN model_inferences i ON i.id = o.inference_id
            WHERE t.id = NEW.trend_id AND t.student_id = NEW.student_id AND o.student_id = NEW.student_id
            AND i.model_version_id = t.model_version_id AND o.dimension = t.dimension
            AND o.observed_at >= t.window_start AND o.observed_at < t.window_end
            AND o.deleted_at IS NULL AND t.deleted_at IS NULL AND i.deleted_at IS NULL
        ) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Trend evidence must match window, dimension and model version'; END IF;
        END""")
    op.execute("""CREATE TRIGGER fusion_evidence_guard BEFORE INSERT ON fusion_inputs
        FOR EACH ROW BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM model_inferences fusion JOIN model_inferences source
                ON source.id = NEW.source_inference_id
            JOIN consent_records c ON c.id = fusion.consent_record_id
            WHERE fusion.id = NEW.fusion_inference_id AND fusion.student_id = NEW.student_id
            AND source.student_id = NEW.student_id AND source.session_id = fusion.session_id
            AND source.processing_status = 'completed' AND source.deleted_at IS NULL
            AND source.modality <> 'multimodal' AND c.withdrawn_at IS NULL
            AND c.version = (SELECT MAX(v.version) FROM consent_records v WHERE v.student_id = NEW.student_id)
            AND ((source.modality = 'text' AND c.text_processing = 1)
              OR (source.modality = 'audio' AND c.audio_processing = 1)
              OR (source.modality = 'visual' AND c.visual_processing = 1))
        ) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Fusion source must be completed, consented and in the same session'; END IF;
        END""")
    op.execute("""CREATE TRIGGER human_review_access BEFORE INSERT ON human_reviews
        FOR EACH ROW BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM reviewer_assignments a JOIN consent_records c ON c.student_id = a.student_id
            JOIN users u ON u.id = a.reviewer_id JOIN reviewer_profiles p ON p.user_id = u.id
            WHERE a.student_id = NEW.student_id AND a.reviewer_id = NEW.reviewer_id
            AND a.revoked_at IS NULL AND c.withdrawn_at IS NULL AND c.reviewer_access = 1
            AND c.version = (SELECT MAX(v.version) FROM consent_records v WHERE v.student_id = NEW.student_id)
            AND u.is_active = 1 AND u.deleted_at IS NULL AND p.deleted_at IS NULL
        ) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Active reviewer assignment and student consent required'; END IF;
        END""")
    op.execute("""CREATE TRIGGER research_split_guard BEFORE INSERT ON research_dataset_records
        FOR EACH ROW BEGIN
        IF EXISTS (
            SELECT 1 FROM research_dataset_records r WHERE r.student_id = NEW.student_id
            AND r.dataset_identifier = NEW.dataset_identifier AND r.dataset_version = NEW.dataset_version
            AND r.split <> NEW.split
        ) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Student cannot span splits within a dataset version'; END IF;
        END""")


def downgrade():
    for table in IMMUTABLE_COLUMNS:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable")
    for name in (
        "research_split_guard",
        "human_review_access",
        "fusion_evidence_guard",
        "trend_evidence_guard",
        "observation_insert_guard",
        "media_update_guard",
        "inference_terminal_guard",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    for table, name, _ in reversed(CHECKS):
        op.drop_constraint(op.f(name), table, type_="check")
