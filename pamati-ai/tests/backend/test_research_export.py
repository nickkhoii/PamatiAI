"""Private synthetic fixtures test export consent and identity minimization, not research results."""

import json

import pytest
from ai.evaluation.contracts import DatasetSpec
from test_auth import api as api_fixture

from app.models import (
    Conversation,
    InteractionSession,
    Message,
    ModelInference,
    ModelVersion,
    ResearchDatasetRecord,
    StudentProfile,
    TextAnalysis,
    User,
    utcnow,
)
from app.persistence import record_consent
from app.research_export import ExportDenied, build_research_export, pseudonym, write_export

api = api_fixture
KEY = b"test-only-export-key-not-a-real-secret-1234"


def descriptor():
    return DatasetSpec(
        identifier="approved-cohort",
        version="1",
        target="sentiment",
        labels=["negative", "positive"],
        positive_label="positive",
        annotation_version="pending-1",
        label_mapping_version="identity-1",
        source_reference="ethics-approved-private-study",
        license_reference="institutional-protocol-1",
        population_scope="institutional_consented",
        evidence_kind="unlabeled",
    )


def populate(api, participants=5, *, first_inference_without_research=False):
    _, db, users, _, _ = api
    model = ModelVersion(model_identifier="fixture-comparator", version="1", modality="text")
    db.add(model)
    db.flush()
    rows = []
    for index in range(participants):
        user = (
            users["alice"]
            if index == 0
            else users["bob"]
            if index == 1
            else User(
                email=f"PRIVATE-{index}@example.com",
                display_name=f"PRIVATE STUDENT {index}",
                password_hash=users["alice"].password_hash,
                is_active=True,
            )
        )
        if index >= 2:
            db.add(user)
            db.flush()
            db.add(StudentProfile(user_id=user.id))
            db.flush()
        consent = record_consent(db, user.id, "fixture", text_processing=True,
                                 research_data_use=not (index == 0 and first_inference_without_research))
        conversation = Conversation(student_id=user.id)
        db.add(conversation)
        db.flush()
        session = InteractionSession(student_id=user.id, conversation_id=conversation.id)
        db.add(session)
        db.flush()
        message = Message(
            student_id=user.id,
            session_id=session.id,
            sender="student",
            sequence_number=0,
            text_content="PRIVATE FREE TEXT",
        )
        db.add(message)
        db.flush()
        now = utcnow()
        inference = ModelInference(
            student_id=user.id,
            session_id=session.id,
            message_id=message.id,
            consent_record_id=consent.id,
            model_version_id=model.id,
            modality="text",
            input_modalities=["text"],
            created_at=now,
            started_at=now,
            completed_at=now,
            processing_status="completed",
            preprocessing_version="1",
            adapter_version="1",
        )
        db.add(inference)
        db.flush()
        db.add(
            TextAnalysis(
                inference_id=inference.id,
                modality="text",
                labels={"sentiment_category": "positive", "abstained": False},
            )
        )
        if index == 0 and first_inference_without_research:
            # Later permission can authorize membership, but cannot relabel old source consent.
            membership_consent = record_consent(db, user.id, "fixture", text_processing=True,
                                                research_data_use=True)
        else:
            membership_consent = consent
        member = ResearchDatasetRecord(
            student_id=user.id,
            inference_id=inference.id,
            consent_record_id=membership_consent.id,
            dataset_identifier="approved-cohort",
            dataset_version="1",
            ethics_approval_reference="approved-study-1",
            deidentification_version="hmac-1",
            split="test",
        )
        db.add(member)
        rows.append((user, consent, inference, member, conversation))
    db.commit()
    return rows


def test_export_contains_no_identifiers_inputs_or_gold_labels(api, tmp_path):
    rows = populate(api)
    export = build_research_export(api[1], descriptor(), KEY)
    assert len(export["rows"]) == 5
    text = json.dumps(export)
    assert "PRIVATE" not in text
    for user, consent, inference, member, _ in rows:
        assert all(
            identifier not in text
            for identifier in [user.id, user.email, consent.id, inference.id, member.id]
        )
    assert all(
        r["observation"]["ground_truth"] is None
        and r["observation"]["origin"] == "AI-generated observation"
        for r in export["rows"]
    )
    write_export(export, tmp_path / "private-export")
    assert (tmp_path / "private-export" / "observations.jsonl").is_file()
    with pytest.raises(FileExistsError):
        write_export(export, tmp_path / "private-export")


@pytest.mark.parametrize(
    "reason", ["withdrawal", "membership", "hidden_source", "processing_disabled"]
)
def test_unconsented_or_hidden_source_is_excluded_then_small_cell_suppressed(api, reason):
    rows = populate(api)
    _, consent, _, membership, conversation = rows[0]
    if reason == "withdrawal":
        consent.withdrawn_at = utcnow()
    elif reason == "membership":
        membership.revoked_at = utcnow()
    elif reason == "hidden_source":
        conversation.deleted_at = utcnow()
    else:
        record_consent(api[1], consent.student_id, "fixture", text_processing=False, research_data_use=True)
    api[1].commit()
    export = build_research_export(api[1], descriptor(), KEY)
    assert export["rows"] == []
    assert export["suppressed_or_excluded_row_count"] >= 4


def test_export_needs_strong_key_and_minimum_cell_size(api):
    with pytest.raises(ExportDenied):
        build_research_export(api[1], descriptor(), b"weak")
    with pytest.raises(ExportDenied):
        build_research_export(api[1], descriptor(), KEY, minimum_group_size=1)
    assert pseudonym(KEY, "a", "1", "participant", "private") != pseudonym(
        KEY, "b", "1", "participant", "private"
    )


def test_original_research_permission_cannot_be_added_retroactively(api):
    populate(api, first_inference_without_research=True)
    assert build_research_export(api[1], descriptor(), KEY)["rows"] == []
