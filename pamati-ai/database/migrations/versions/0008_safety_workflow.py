"""Safety workflow provenance, concurrency state and literal-message evidence."""
import sqlalchemy as sa
from alembic import op

revision = "0008_safety_workflow"
down_revision = "0007_conversation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("risk_signals", sa.Column("source_message_id", sa.String(36), nullable=True))
    op.add_column("risk_signals", sa.Column("consent_record_id", sa.String(36), nullable=True))
    op.add_column("risk_signals", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("risk_signals", sa.Column("workflow_state", sa.String(12), nullable=False, server_default="new"))
    op.add_column("risk_signals", sa.Column("assigned_reviewer_id", sa.String(36), nullable=True))
    op.add_column("risk_signals", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.create_foreign_key("fk_risk_signals_source_message_id_messages", "risk_signals", "messages", ["source_message_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_risk_signals_consent_record_id_consent_records", "risk_signals", "consent_records", ["consent_record_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_risk_signals_assigned_reviewer_id_reviewer_profiles", "risk_signals", "reviewer_profiles", ["assigned_reviewer_id"], ["user_id"], ondelete="RESTRICT")
    op.drop_constraint(op.f("ck_risk_signals_signal_source"), "risk_signals", type_="check")
    op.create_check_constraint(op.f("ck_risk_signals_signal_source"), "risk_signals", "inference_id IS NOT NULL OR trend_id IS NOT NULL OR source_message_id IS NOT NULL")
    op.create_check_constraint(op.f("ck_risk_signals_signal_confidence"), "risk_signals", "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)")
    op.create_check_constraint(op.f("ck_risk_signals_safety_workflow_state"), "risk_signals", "workflow_state IN ('new','under_review','resolved','referred')")
    op.create_unique_constraint("uq_risk_signals_source_message_id_signal_code_rule_version", "risk_signals", ["source_message_id", "signal_code", "rule_version"])
    op.add_column("human_reviews", sa.Column("workflow_from", sa.String(20), nullable=True))
    op.add_column("human_reviews", sa.Column("workflow_to", sa.String(20), nullable=True))
    op.add_column("human_reviews", sa.Column("signal_revision", sa.Integer(), nullable=True))
    op.drop_constraint(op.f("ck_human_reviews_review_decision"), "human_reviews", type_="check")
    op.alter_column("human_reviews", "decision", existing_type=sa.String(11), type_=sa.String(11), existing_nullable=False)
    op.create_check_constraint(op.f("ck_human_reviews_review_decision"), "human_reviews", "decision IN ('acknowledge','dismiss','follow_up','refer','resolve','reopen')")
    op.execute("""UPDATE risk_signals s SET workflow_state = CASE
        WHEN status IN ('resolved','dismissed') THEN 'resolved'
        WHEN EXISTS (SELECT 1 FROM human_reviews h JOIN referral_records r ON r.human_review_id=h.id
                     WHERE h.risk_signal_id=s.id AND r.deleted_at IS NULL) THEN 'referred'
        WHEN status='acknowledged' OR EXISTS (SELECT 1 FROM human_reviews h WHERE h.risk_signal_id=s.id)
        THEN 'under_review' ELSE 'new' END""")
    op.execute("""UPDATE risk_signals s SET assigned_reviewer_id=(SELECT h.reviewer_id FROM human_reviews h
        WHERE h.risk_signal_id=s.id ORDER BY h.created_at DESC, h.id DESC LIMIT 1)
        WHERE workflow_state <> 'new'""")
    op.execute("""CREATE TRIGGER safety_message_source_guard BEFORE INSERT ON risk_signals
        FOR EACH ROW BEGIN
        IF NEW.source_message_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM messages m JOIN interaction_sessions s ON s.id=m.session_id
          JOIN conversations v ON v.id=s.conversation_id JOIN consent_records c ON c.id=NEW.consent_record_id
          WHERE m.id=NEW.source_message_id AND m.student_id=NEW.student_id AND m.sender='student'
          AND m.deleted_at IS NULL AND s.deleted_at IS NULL AND v.deleted_at IS NULL
          AND c.student_id=NEW.student_id AND c.withdrawn_at IS NULL AND c.text_processing=1
          AND c.version=(SELECT MAX(latest.version) FROM consent_records latest WHERE latest.student_id=NEW.student_id)
        ) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Current text consent and live owned safety message required'; END IF;
        END""")
    op.execute("""CREATE TRIGGER safety_provenance_guard BEFORE UPDATE ON risk_signals
        FOR EACH ROW BEGIN
        IF NOT (NEW.student_id <=> OLD.student_id) OR NOT (NEW.source_message_id <=> OLD.source_message_id)
           OR NOT (NEW.consent_record_id <=> OLD.consent_record_id) OR NOT (NEW.inference_id <=> OLD.inference_id)
           OR NOT (NEW.trend_id <=> OLD.trend_id) OR NOT (NEW.rule_version <=> OLD.rule_version)
           OR NOT (NEW.signal_code <=> OLD.signal_code) OR NOT (NEW.confidence <=> OLD.confidence)
        THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Safety provenance is immutable'; END IF;
        END""")


def downgrade():
    # Restoring old checks first refuses to silently discard new source-only records or review decisions.
    op.create_check_constraint(op.f("ck_risk_signals_legacy_source"), "risk_signals", "inference_id IS NOT NULL OR trend_id IS NOT NULL")
    op.create_check_constraint(op.f("ck_human_reviews_legacy_decision"), "human_reviews", "decision IN ('acknowledge','dismiss','follow_up','refer')")
    op.execute("DROP TRIGGER safety_provenance_guard")
    op.execute("DROP TRIGGER safety_message_source_guard")
    op.drop_constraint(op.f("ck_risk_signals_legacy_source"), "risk_signals", type_="check")
    op.drop_constraint(op.f("ck_human_reviews_legacy_decision"), "human_reviews", type_="check")
    op.drop_constraint(op.f("ck_human_reviews_review_decision"), "human_reviews", type_="check")
    op.create_check_constraint(op.f("ck_human_reviews_review_decision"), "human_reviews", "decision IN ('acknowledge','dismiss','follow_up','refer')")
    for column in ("signal_revision", "workflow_from", "workflow_to"):
        op.drop_column("human_reviews", column)
    for constraint in ("uq_risk_signals_source_message_id_signal_code_rule_version",):
        op.drop_constraint(constraint, "risk_signals", type_="unique")
    for constraint in ("ck_risk_signals_signal_source", "ck_risk_signals_signal_confidence", "ck_risk_signals_safety_workflow_state"):
        op.drop_constraint(op.f(constraint), "risk_signals", type_="check")
    op.create_check_constraint(op.f("ck_risk_signals_signal_source"), "risk_signals", "inference_id IS NOT NULL OR trend_id IS NOT NULL")
    for name in ("fk_risk_signals_source_message_id_messages", "fk_risk_signals_consent_record_id_consent_records", "fk_risk_signals_assigned_reviewer_id_reviewer_profiles"):
        op.drop_constraint(name, "risk_signals", type_="foreignkey")
    for column in ("source_message_id", "consent_record_id", "confidence", "workflow_state", "assigned_reviewer_id", "revision"):
        op.drop_column("risk_signals", column)
