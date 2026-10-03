"""Real MySQL tests, explicitly enabled using TEST_DATABASE_URL ending in _test."""

import os
from datetime import timedelta

import pytest
from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database_commands import DEVELOPMENT_EMAILS, ROLE_PERMISSIONS, seed
from app.models import (
    AudioAnalysis,
    AuditLog,
    Base,
    ConsentRecord,
    Conversation,
    InteractionSession,
    MediaAsset,
    Message,
    ModelInference,
    ModelVersion,
    ResearchDatasetRecord,
    Role,
    SentimentTrend,
    StudentProfile,
    SystemSetting,
    User,
    utcnow,
)
from app.persistence import (
    ConsentDenied,
    create_inference,
    record_consent,
    retain_media,
    withdraw_consent,
)


@pytest.fixture(scope="module")
def mysql_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL for real MySQL tests")
    parsed = make_url(url)
    if parsed.drivername != "mysql+pymysql" or not (parsed.database or "").endswith("_test"):
        pytest.fail("Integration tests require a dedicated mysql+pymysql database ending in _test")
    # This suite never drops tables or deletes committed data.
    config = Config("alembic.ini")
    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        command.upgrade(config, "head")
    finally:
        if old_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_url
        get_settings.cache_clear()
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(mysql_engine):
    with mysql_engine.connect() as connection:
        transaction = connection.begin()
        with Session(connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


def graph(db, *, modality="text", **permissions):
    from app.models import identifier

    user = User(
        email=f"{identifier()}@test.example",
        display_name="Test student 🙂",
        password_hash="not-an-authentication-fixture",
    )
    db.add(user)
    db.flush()
    db.add(StudentProfile(user_id=user.id))
    db.flush()
    receipt = record_consent(db, user.id, "test-policy-v1", **permissions)
    conversation = Conversation(student_id=user.id)
    db.add(conversation)
    db.flush()
    interaction = InteractionSession(student_id=user.id, conversation_id=conversation.id)
    db.add(interaction)
    db.flush()
    message = Message(
        session_id=interaction.id,
        student_id=user.id,
        sequence_number=0,
        sender="student",
        text_content="Kumusta 🙂 你好",
    )
    model = ModelVersion(
        model_identifier=f"test/{identifier()}",
        version="revision-1",
        modality=modality,
        configuration={"fixture": True},
    )
    db.add_all([message, model])
    db.flush()
    return user, receipt, interaction, message, model


def infer(db, data):
    user, _, interaction, message, model = data
    return create_inference(
        db,
        student_id=user.id,
        session_id=interaction.id,
        message_id=message.id,
        model_version_id=model.id,
        preprocessing_version="pre-v1",
        adapter_version="adapter-v1",
    )


def test_all_entities_are_migrated(mysql_engine):
    assert set(Base.metadata.tables) <= set(inspect(mysql_engine).get_table_names())
    with mysql_engine.connect() as connection:
        collations = connection.execute(
            text(
                "SELECT table_collation FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name <> 'alembic_version'"
            )
        )
        assert all(row[0] == "utf8mb4_0900_ai_ci" for row in collations)


def test_unicode_text_chat_without_optional_consent(db):
    _, receipt, _, message, _ = graph(db)
    db.expire_all()
    assert db.get(Message, message.id).text_content == "Kumusta 🙂 你好"
    assert not receipt.audio_processing and not receipt.visual_processing
    with pytest.raises(ConsentDenied):
        infer(
            db,
            (
                message.session.conversation.student.user,
                receipt,
                message.session,
                message,
                db.scalar(select(ModelVersion).limit(1)),
            ),
        )


@pytest.mark.parametrize("modality", ["audio", "visual"])
def test_declining_optional_modalities_does_not_block_text(db, modality):
    data = graph(db, text_processing=True)
    assert infer(db, data).modality == "text"
    optional_model = ModelVersion(model_identifier="optional-test", version="v1", modality=modality)
    db.add(optional_model)
    db.flush()
    with pytest.raises(ConsentDenied):
        create_inference(
            db,
            student_id=data[0].id,
            session_id=data[2].id,
            model_version_id=optional_model.id,
            preprocessing_version="pre-v1",
            adapter_version="adapter-v1",
        )


def test_cross_student_conversation_is_rejected_by_mysql(db):
    first = graph(db)
    second = graph(db)
    db.add(InteractionSession(conversation_id=first[2].conversation_id, student_id=second[0].id))
    with pytest.raises(DBAPIError):
        db.flush()


def test_cross_student_message_is_rejected_by_mysql(db):
    first = graph(db)
    second = graph(db)
    db.add(
        Message(
            session_id=first[2].id,
            student_id=second[0].id,
            sender="student",
            sequence_number=1,
            text_content="test",
        )
    )
    with pytest.raises(DBAPIError):
        db.flush()


def test_inference_provenance_and_confidence(db):
    data = graph(db, text_processing=True)
    inference = infer(db, data)
    assert inference.model.model_identifier == data[4].model_identifier
    assert inference.model.version == "revision-1"
    assert inference.processing_status == "pending"
    assert inference.confidence is None and inference.uncertainty is None
    assert inference.created_at is not None
    inference.confidence = 1.5
    with pytest.raises(DBAPIError):
        db.flush()


def test_inference_model_provenance_cannot_be_rewritten(db):
    inference = infer(db, graph(db, text_processing=True))
    inference.adapter_version = "silently-changed"
    with pytest.raises(DBAPIError):
        db.flush()


def test_wrong_analysis_modality_is_rejected(db):
    inference = infer(db, graph(db, text_processing=True))
    db.add(AudioAnalysis(inference_id=inference.id, modality="audio", labels={}))
    with pytest.raises(DBAPIError):
        db.flush()


def test_new_consent_version_supersedes_old_grants(db):
    data = graph(db, text_processing=True)
    receipt = record_consent(db, data[0].id, "policy-v2")
    assert receipt.version == 2 and not receipt.text_processing
    with pytest.raises(ConsentDenied):
        infer(db, data)


def test_mysql_blocks_direct_inference_with_superseded_receipt(db):
    data = graph(db, text_processing=True)
    record_consent(db, data[0].id, "policy-v2")
    db.add(
        ModelInference(
            student_id=data[0].id,
            session_id=data[2].id,
            consent_record_id=data[1].id,
            model_version_id=data[4].id,
            modality="text",
            preprocessing_version="v1",
            adapter_version="v1",
        )
    )
    with pytest.raises(DBAPIError):
        db.flush()


def test_withdrawal_cancels_jobs_and_blocks_processing(db):
    data = graph(db, text_processing=True)
    inference = infer(db, data)
    withdraw_consent(db, data[0].id)
    assert inference.processing_status == "cancelled"
    inference.processing_status = "running"
    with pytest.raises(DBAPIError):
        db.flush()


def test_consent_receipts_cannot_be_silently_modified(db):
    data = graph(db)
    data[1].audio_processing = True
    with pytest.raises(DBAPIError):
        db.flush()


def test_deleting_latest_consent_cannot_reactivate_old_grant(db):
    data = graph(db, text_processing=True)
    declined = record_consent(db, data[0].id, "policy-v2")
    db.delete(declined)
    with pytest.raises(DBAPIError):
        db.flush()


def test_raw_media_disabled_without_environment_opt_in(db):
    data = graph(db, audio_processing=True, retain_audio=True)
    with pytest.raises(ConsentDenied):
        retain_media(
            db,
            Settings(),
            student_id=data[0].id,
            session_id=data[2].id,
            modality="audio",
            storage_reference="opaque-test-ref",
            expires_at=utcnow() + timedelta(minutes=5),
        )


def test_mysql_requires_raw_media_configuration(db):
    data = graph(db, audio_processing=True, retain_audio=True)
    db.add(
        MediaAsset(
            student_id=data[0].id,
            session_id=data[2].id,
            consent_record_id=data[1].id,
            modality="audio",
            storage_reference="opaque-test-ref",
            expires_at=utcnow() + timedelta(minutes=5),
        )
    )
    with pytest.raises(DBAPIError):
        db.flush()


def test_expiring_media_reference_requires_both_configuration_and_consent(db):
    seed(db)
    db.get(SystemSetting, "raw_media_retention").value = {"enabled": True}
    db.flush()
    data = graph(db, audio_processing=True, retain_audio=True)
    asset = retain_media(
        db,
        Settings(allow_raw_media_storage=True),
        student_id=data[0].id,
        session_id=data[2].id,
        modality="audio",
        storage_reference="opaque-reference",
        expires_at=utcnow() + timedelta(minutes=5),
    )
    assert asset.expires_at > asset.created_at
    assert not any(
        "blob" in column.name or "raw" in column.name for column in MediaAsset.__table__.columns
    )


def test_research_use_requires_separate_consent(db):
    data = graph(db, text_processing=True)
    inference = infer(db, data)
    db.add(
        ResearchDatasetRecord(
            student_id=data[0].id,
            inference_id=inference.id,
            consent_record_id=data[1].id,
            dataset_identifier="test-dataset",
            dataset_version="1",
            ethics_approval_reference="test-only",
            deidentification_version="1",
            split="test",
        )
    )
    with pytest.raises(DBAPIError):
        db.flush()


def test_longitudinal_tracking_requires_separate_consent(db):
    data = graph(db, text_processing=True)
    db.add(
        SentimentTrend(
            student_id=data[0].id,
            consent_record_id=data[1].id,
            model_version_id=data[4].id,
            dimension="valence",
            window_start=utcnow(),
            window_end=utcnow() + timedelta(days=1),
            algorithm_version="test-v1",
            sample_count=1,
            summary={},
        )
    )
    with pytest.raises(DBAPIError):
        db.flush()


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_audit_is_append_only(db, operation):
    audit = AuditLog(action="test", resource_type="test", outcome="success")
    db.add(audit)
    db.flush()
    if operation == "update":
        audit.action = "changed"
    else:
        db.delete(audit)
    with pytest.raises(DBAPIError):
        db.flush()


def test_development_seed_is_idempotent_and_uses_argon2(db, monkeypatch):
    from app.models import identifier

    for role_code in DEVELOPMENT_EMAILS:
        monkeypatch.setitem(DEVELOPMENT_EMAILS, role_code, f"{identifier()}@dev-test.example")
    password = "test-only-long-secret-value"
    seed(db, development_accounts=True, password=password, environment="development")
    count = db.scalar(select(func.count()).select_from(User))
    hashes = {user.email: user.password_hash for user in db.scalars(select(User))}
    seed(
        db, development_accounts=True, password="different-long-password", environment="development"
    )
    assert db.scalar(select(func.count()).select_from(User)) == count
    for user in db.scalars(select(User).where(User.email.in_(DEVELOPMENT_EMAILS.values()))):
        assert user.is_development_account
        assert user.display_name.startswith("[DEVELOPMENT ONLY]")
        assert user.password_hash == hashes[user.email]
        assert PasswordHasher().verify(user.password_hash, password)
    for role in db.scalars(select(Role)):
        assert {permission.code for permission in role.permissions} == ROLE_PERMISSIONS[role.code]
    student = db.scalar(select(User).where(User.email == DEVELOPMENT_EMAILS["STUDENT"]))
    assert not db.scalar(
        select(func.count())
        .select_from(ConsentRecord)
        .where(ConsentRecord.student_id == student.id)
    )


def complete(inference):
    inference.started_at = utcnow()
    inference.completed_at = utcnow()
    inference.processing_status = "completed"
    inference.confidence = 0.75
    inference.uncertainty = {"fixture": True, "entropy": 0.4}
    inference.uncertainty_method = "fixture-entropy-v1"


def test_completed_inference_cannot_be_reopened(db):
    inference = infer(db, graph(db, text_processing=True))
    complete(inference)
    db.flush()
    inference.processing_status = "pending"
    with pytest.raises(DBAPIError):
        db.flush()


def test_completed_inference_requires_timestamps(db):
    inference = infer(db, graph(db, text_processing=True))
    inference.processing_status = "completed"
    with pytest.raises(DBAPIError):
        db.flush()


def test_model_version_is_immutable(db):
    data = graph(db)
    data[4].version = "rewritten-version"
    with pytest.raises(DBAPIError):
        db.flush()


def test_complete_support_review_and_longitudinal_evidence_graph(db):
    from app.models import (
        HumanReview,
        ReferralRecord,
        ReviewerAssignment,
        RiskSignal,
        SentimentObservation,
        TextAnalysis,
        TrendObservation,
    )

    seed(
        db, development_accounts=True, password="long-test-only-password", environment="development"
    )
    data = graph(
        db,
        text_processing=True,
        longitudinal_tracking=True,
        reviewer_access=True,
        research_data_use=True,
    )
    inference = infer(db, data)
    complete(inference)
    db.flush()
    db.add(TextAnalysis(inference_id=inference.id, modality="text", labels={"fixture": 0.75}))
    observed_at = utcnow()
    observation = SentimentObservation(
        student_id=data[0].id,
        inference_id=inference.id,
        dimension="valence",
        score=0.1,
        observed_at=observed_at,
    )
    trend = SentimentTrend(
        student_id=data[0].id,
        consent_record_id=data[1].id,
        model_version_id=data[4].id,
        dimension="valence",
        window_start=observed_at - timedelta(days=1),
        window_end=observed_at + timedelta(days=1),
        algorithm_version="test-only-v1",
        sample_count=1,
        summary={"fixture": True},
    )
    db.add_all([observation, trend])
    db.flush()
    db.add(
        TrendObservation(trend_id=trend.id, observation_id=observation.id, student_id=data[0].id)
    )
    signal = RiskSignal(
        student_id=data[0].id,
        inference_id=inference.id,
        trend_id=trend.id,
        signal_code="test-support-only",
        priority="routine",
        explanation={"fixture": True},
        rule_version="test-only-v1",
    )
    db.add(signal)
    db.flush()
    reviewer = db.scalar(select(User).where(User.email == DEVELOPMENT_EMAILS["COUNSELOR"]))
    admin = db.scalar(select(User).where(User.email == DEVELOPMENT_EMAILS["ADMIN"]))
    db.add(ReviewerAssignment(student_id=data[0].id, reviewer_id=reviewer.id, assigned_by=admin.id))
    db.flush()
    review = HumanReview(
        student_id=data[0].id,
        risk_signal_id=signal.id,
        reviewer_id=reviewer.id,
        decision="refer",
        notes="Test fixture only",
    )
    db.add(review)
    db.flush()
    db.add(
        ReferralRecord(
            student_id=data[0].id,
            human_review_id=review.id,
            service_reference="test-service",
            status="offered",
        )
    )
    research = ResearchDatasetRecord(
        student_id=data[0].id,
        inference_id=inference.id,
        consent_record_id=data[1].id,
        dataset_identifier="fixture-dataset",
        dataset_version="v1",
        ethics_approval_reference="fixture-only",
        deidentification_version="v1",
        split="test",
    )
    db.add(research)
    db.flush()
    assert review.risk_signal.status == "pending_review"
    withdraw_consent(db, data[0].id)
    assert research.revoked_at is not None


def test_observations_require_completed_inference(db):
    from app.models import SentimentObservation

    data = graph(db, text_processing=True, longitudinal_tracking=True)
    inference = infer(db, data)
    db.add(
        SentimentObservation(
            student_id=data[0].id,
            inference_id=inference.id,
            dimension="valence",
            score=0.1,
            observed_at=utcnow(),
        )
    )
    with pytest.raises(DBAPIError):
        db.flush()


def test_reviewer_without_assignment_cannot_record_decision(db):
    from app.models import HumanReview, RiskSignal

    seed(
        db, development_accounts=True, password="long-test-only-password", environment="development"
    )
    data = graph(db, text_processing=True, reviewer_access=True)
    inference = infer(db, data)
    signal = RiskSignal(
        student_id=data[0].id,
        inference_id=inference.id,
        signal_code="test",
        priority="routine",
        explanation={},
        rule_version="fixture-v1",
    )
    db.add(signal)
    db.flush()
    reviewer = db.scalar(select(User).where(User.email == DEVELOPMENT_EMAILS["COUNSELOR"]))
    db.add(
        HumanReview(
            student_id=data[0].id,
            risk_signal_id=signal.id,
            reviewer_id=reviewer.id,
            decision="acknowledge",
        )
    )
    with pytest.raises(DBAPIError):
        db.flush()


def test_text_only_fusion_preserves_missing_optional_modalities(db):
    from app.models import FusionInput, MultimodalAnalysis

    data = graph(db, text_processing=True)
    source = infer(db, data)
    complete(source)
    fusion_model = ModelVersion(model_identifier="test-fusion", version="v1", modality="multimodal")
    db.add(fusion_model)
    db.flush()
    fusion = create_inference(
        db,
        student_id=data[0].id,
        session_id=data[2].id,
        model_version_id=fusion_model.id,
        preprocessing_version="v1",
        adapter_version="v1",
    )
    db.add(
        MultimodalAnalysis(
            inference_id=fusion.id,
            modality="multimodal",
            labels={},
            fusion_strategy_version="test-v1",
            missing_modalities=["audio", "visual"],
        )
    )
    db.flush()
    db.add(
        FusionInput(
            fusion_inference_id=fusion.id, source_inference_id=source.id, student_id=data[0].id
        )
    )
    db.flush()


def test_media_retention_cannot_be_extended_by_update(db):
    seed(db)
    db.get(SystemSetting, "raw_media_retention").value = {"enabled": True}
    db.flush()
    data = graph(db, audio_processing=True, retain_audio=True)
    asset = retain_media(
        db,
        Settings(allow_raw_media_storage=True),
        student_id=data[0].id,
        session_id=data[2].id,
        modality="audio",
        storage_reference="test-expiry-ref",
        expires_at=utcnow() + timedelta(minutes=5),
    )
    asset.expires_at += timedelta(days=100)
    with pytest.raises(DBAPIError):
        db.flush()


def test_development_seed_prohibited_in_production(db):
    with pytest.raises(ValueError, match="prohibited"):
        seed(
            db, development_accounts=True, password="long-enough-password", environment="production"
        )


def test_duplicate_message_sequence_is_rejected(db):
    data = graph(db)
    db.add(
        Message(
            session_id=data[2].id,
            student_id=data[0].id,
            sender="student",
            sequence_number=0,
            text_content="duplicate",
        )
    )
    with pytest.raises(DBAPIError):
        db.flush()
