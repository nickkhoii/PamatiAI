from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from test_auth import api as shared_api
from test_auth import headers

from app.consent_policy import POLICY_VERSION
from app.models import ConsentRecord, ModelInference, ModelVersion, TextAnalysis, utcnow
from app.persistence import ConsentDenied, create_inference, record_consent, withdraw_consent
from app.processing import run_analysis
from app.retention import deadline, retention_policy

api = shared_api  # Register the shared fixture under its original pytest name.


def body(**choices):
    return {
        "policy_version": POLICY_VERSION,
        "acknowledged": True,
        "retention_version": 1,
        **choices,
    }


def job(api, modality="text", inputs=None):
    from app.models import InteractionSession

    db, student = api[1], api[2]["alice"]
    model = ModelVersion(
        model_identifier=f"test-{modality}-{utcnow().isoformat()}", version="1", modality=modality
    )
    db.add(model)
    db.flush()
    interaction = db.scalar(
        select(InteractionSession).where(InteractionSession.student_id == student.id)
    )
    return create_inference(
        db,
        student_id=student.id,
        session_id=interaction.id,
        model_version_id=model.id,
        preprocessing_version="1",
        adapter_version="1",
        input_modalities=inputs,
    )


def test_informed_consent_evidence_defaults_and_optimistic_version(api):
    client, db, users, _, _ = api
    auth = headers(api, "alice")
    document = client.get("/api/v1/me/onboarding", headers=auth).json()
    assert not document["completed"]
    assert len(document["policy"]["disclosures"]) == 10
    path = f"/api/v1/students/{users['alice'].id}/consent"
    assert (
        client.put(path, headers=auth, json={"policy_version": POLICY_VERSION}).status_code == 409
    )
    assert client.put(path, headers=auth, json=body(policy_version="outdated")).status_code == 409
    response = client.put(path, headers=auth, json=body(text_processing=True, expected_version=1))
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["version"] == 2 and receipt["created_at"]
    assert receipt["disclosure_snapshot"]["version"] == POLICY_VERSION
    assert receipt["disclosure_snapshot"]["retention"]["raw_media_hours"] == 24
    for flag in [
        "audio_processing",
        "visual_processing",
        "longitudinal_tracking",
        "research_data_use",
    ]:
        assert receipt[flag] is False
    assert client.put(path, headers=auth, json=body(expected_version=1)).status_code == 409
    assert client.get("/api/v1/me/onboarding", headers=auth).json()["completed"]
    assert (
        db.scalar(
            select(ConsentRecord).where(
                ConsentRecord.student_id == users["alice"].id, ConsentRecord.version == 1
            )
        ).policy_version
        == "v1"
    )


@pytest.mark.parametrize("modality", ["text", "audio", "visual"])
def test_disabled_modality_cannot_be_enqueued(api, modality):
    db, user = api[1], api[2]["alice"]
    record_consent(db, user.id, POLICY_VERSION)
    with pytest.raises(ConsentDenied):
        job(api, modality)
    assert not list(db.scalars(select(ModelInference)))


@pytest.mark.parametrize("modality", ["text", "audio", "visual"])
def test_disabling_queued_modality_prevents_adapter_execution(api, modality):
    db, user = api[1], api[2]["alice"]
    record_consent(db, user.id, POLICY_VERSION, **{f"{modality}_processing": True})
    queued = job(api, modality)
    db.commit()
    record_consent(db, user.id, POLICY_VERSION)
    db.commit()
    adapter = Mock()
    assert run_analysis(db, queued.id, adapter, {modality: "opaque-reference"}) is None
    adapter.analyze.assert_not_called()
    assert queued.processing_status == "cancelled"


def test_optional_payload_cannot_be_smuggled_into_text_only_fusion(api):
    db, user = api[1], api[2]["alice"]
    record_consent(db, user.id, POLICY_VERSION, text_processing=True)
    with pytest.raises(ConsentDenied):
        job(api, "multimodal", ["text", "audio"])
    queued = job(api, "multimodal")
    assert queued.input_modalities == ["text"]
    db.commit()
    adapter = Mock()
    assert (
        run_analysis(db, queued.id, adapter, {"text": "message-ref", "audio": "audio-ref"}) is None
    )
    adapter.analyze.assert_not_called()


def test_enabled_text_reaches_adapter_and_saves_result(api):
    db, user = api[1], api[2]["alice"]
    record_consent(db, user.id, POLICY_VERSION, text_processing=True)
    queued = job(api)
    db.commit()
    adapter = Mock()
    adapter.analyze.return_value = SimpleNamespace(
        labels={"neutral": 0.7}, limitations=["test only"]
    )
    assert run_analysis(db, queued.id, adapter, {"text": "message-ref"}) == queued.id
    sample = adapter.analyze.call_args.args[0]
    assert sample.payload_references == {"text": "message-ref"}
    assert db.get(TextAnalysis, queued.id).labels == {"neutral": 0.7}


def test_withdrawal_during_adapter_discards_output(api):
    db, user = api[1], api[2]["alice"]
    record_consent(db, user.id, POLICY_VERSION, text_processing=True)
    queued = job(api)
    db.commit()

    def analyze(_):
        withdraw_consent(db, user.id)
        db.commit()
        return SimpleNamespace(labels={"neutral": 0.7}, limitations=[])

    adapter = Mock()
    adapter.analyze.side_effect = analyze
    assert run_analysis(db, queued.id, adapter, {"text": "message-ref"}) is None
    assert db.get(TextAnalysis, queued.id) is None
    assert db.get(ModelInference, queued.id).processing_status == "cancelled"


def test_decline_all_and_withdrawal_preserve_privacy_and_support(api):
    client, _, users, records, _ = api
    auth = headers(api, "alice")
    base = f"/api/v1/students/{users['alice'].id}"
    assert client.put(base + "/consent", headers=auth, json=body()).status_code == 200
    assert client.post(base + "/conversations", headers=auth).status_code == 409
    assert client.get(base + "/privacy", headers=auth).status_code == 200
    assert client.post(base + "/support-requests", headers=auth).status_code == 201
    assert client.delete(base + "/consent", headers=auth).status_code == 204
    assert client.delete(base + "/consent", headers=auth).status_code == 204
    assert client.get(base + "/records?category=analysis", headers=auth).status_code == 200
    assert (
        client.get(f"/api/v1/conversations/{records['alice'].id}", headers=auth).status_code == 200
    )
    request = client.post(base + "/data-controls", headers=auth, json={"kind": "export"})
    assert request.status_code == 202 and request.json()["review_due_at"]


@pytest.mark.parametrize("path", ["privacy", "records?category=research", "consent/history"])
@pytest.mark.parametrize("actor", ["bob", "counselor", "admin"])
def test_student_privacy_views_are_owner_only(api, path, actor):
    response = api[0].get(
        f"/api/v1/students/{api[2]['alice'].id}/{path}", headers=headers(api, actor)
    )
    assert response.status_code == 403


def test_finite_holds_are_visible_and_required_for_erasure_deferral(api):
    client, db, users, _, _ = api
    student = headers(api, "alice")
    admin = headers(api, "admin")
    base = f"/api/v1/students/{users['alice'].id}"
    request = client.post(base + "/data-controls", headers=student, json={"kind": "erasure"}).json()
    path = f"/api/v1/admin/data-controls/{request['id']}"
    assert (
        client.patch(
            path,
            headers=admin,
            json={"status": "deferred", "reason": "Approved institutional restriction"},
        ).status_code
        == 409
    )
    hold = {
        "category": "conversations",
        "reason": "Example approved institutional retention",
        "legal_basis": "Example institutional order reference",
        "expires_at": (datetime.now(UTC) + timedelta(days=400)).isoformat(),
    }
    response = client.post(
        f"/api/v1/admin/students/{users['alice'].id}/retention-holds", headers=admin, json=hold
    )
    assert response.status_code == 201
    assert (
        client.get(base + "/privacy", headers=student).json()["holds"][0]["reason"]
        == hold["reason"]
    )
    assert (
        client.patch(
            path, headers=admin, json={"status": "deferred", "reason": hold["reason"]}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            path,
            headers=admin,
            json={"status": "fulfilled", "reason": "Unverified claim of deletion"},
        ).status_code
        == 422
    )
    assert (
        client.get(f"/api/v1/conversations/{api[3]['alice'].id}", headers=admin).status_code == 403
    )
    assert (
        client.delete(
            f"/api/v1/admin/retention-holds/{response.json()['id']}", headers=admin
        ).status_code
        == 204
    )
    assert not client.get(base + "/privacy", headers=student).json()["holds"]
    saved = retention_policy(db).model_dump()
    original = deadline(db, users["alice"].id, "conversations", utcnow(), snapshot=saved)
    saved["conversation_days"] = 30
    earlier = deadline(db, users["alice"].id, "conversations", utcnow(), snapshot=saved)
    assert earlier < original


def test_retention_config_validation_and_raw_cap(api):
    from app.config import Settings
    from app.models import InteractionSession, SystemSetting
    from app.persistence import retain_media

    client, db, users, _, _ = api
    admin = headers(api, "admin")
    path = "/api/v1/admin/settings/data_retention"
    assert (
        client.put(path, headers=admin, json={"value": {"raw_media_hours": -1}}).status_code == 422
    )
    assert (
        client.put(path, headers=admin, json={"value": {"raw_media_hours": 1}}).status_code == 200
    )
    db.get(SystemSetting, "raw_media_retention").value = {"enabled": True}
    record_consent(db, users["alice"].id, POLICY_VERSION, audio_processing=True, retain_audio=True)
    interaction = db.scalar(
        select(InteractionSession).where(InteractionSession.student_id == users["alice"].id)
    )
    with pytest.raises(ConsentDenied, match="configured limit"):
        retain_media(
            db,
            Settings(allow_raw_media_storage=True),
            student_id=users["alice"].id,
            session_id=interaction.id,
            modality="audio",
            storage_reference="opaque",
            expires_at=utcnow() + timedelta(hours=2),
        )


def test_tracking_and_research_services_require_independent_consent(api):
    from app.persistence import create_trend, register_research_use

    db, user = api[1], api[2]["alice"]
    record_consent(db, user.id, POLICY_VERSION, text_processing=True)
    with pytest.raises(ConsentDenied, match="longitudinal"):
        create_trend(db, student_id=user.id)
    with pytest.raises(ConsentDenied, match="research"):
        register_research_use(db, student_id=user.id)


def test_withdrawal_shortens_raw_retention_without_claiming_physical_deletion(api):
    from app.config import Settings
    from app.models import InteractionSession, SystemSetting
    from app.persistence import retain_media

    db, user = api[1], api[2]["alice"]
    db.get(SystemSetting, "raw_media_retention").value = {"enabled": True}
    record_consent(db, user.id, POLICY_VERSION, audio_processing=True, retain_audio=True)
    interaction = db.scalar(
        select(InteractionSession).where(InteractionSession.student_id == user.id)
    )
    asset = retain_media(
        db,
        Settings(allow_raw_media_storage=True),
        student_id=user.id,
        session_id=interaction.id,
        modality="audio",
        storage_reference="withdrawal-test-ref",
        expires_at=utcnow() + timedelta(hours=1),
    )
    old = asset.expires_at
    withdraw_consent(db, user.id)
    db.flush()
    assert asset.expires_at < old and asset.purged_at is None


def test_retention_report_excludes_held_records_without_deleting_content(api):
    from app.models import RetentionHold
    from app.retention_report import report

    db, user, conversation = api[1], api[2]["alice"], api[3]["alice"]
    conversation.created_at = utcnow() - timedelta(days=200)
    db.flush()
    assert report(db)["conversations"]["due_for_review"] == 1
    hold = RetentionHold(
        student_id=user.id,
        category="conversations",
        reason="Example documented institutional obligation",
        legal_basis="Example order reference",
        expires_at=utcnow() + timedelta(days=10),
        created_by=api[2]["admin"].id,
    )
    db.add(hold)
    db.flush()
    assert report(db)["conversations"] == {"due_for_review": 0, "held": 1}
    assert conversation.deleted_at is None


def test_mysql_disclosures_and_manifest_are_immutable(api):
    if api[1].bind.dialect.name != "mysql":
        pytest.skip("MySQL evidence triggers are exercised against MySQL only")
    from sqlalchemy.exc import DBAPIError

    client, db, users, _, _ = api
    path = f"/api/v1/students/{users['alice'].id}/consent"
    response = client.put(path, headers=headers(api, "alice"), json=body(text_processing=True))
    receipt = db.get(ConsentRecord, response.json()["id"])
    with pytest.raises(DBAPIError), db.begin_nested():
        receipt.disclosure_snapshot = {"version": "silently altered"}
        db.flush()
    db.expire_all()
    queued = job(api)
    with pytest.raises(DBAPIError), db.begin_nested():
        queued.input_modalities = ["audio"]
        db.flush()


def test_changed_retention_policy_requires_student_to_review_new_information(api):
    client, _, users, _, _ = api
    student = headers(api, "alice")
    shown = client.get("/api/v1/me/onboarding", headers=student).json()["retention"]
    admin = headers(api, "admin")
    changed = {**shown, "conversation_days": 90}
    assert (
        client.put(
            "/api/v1/admin/settings/data_retention", headers=admin, json={"value": changed}
        ).status_code
        == 200
    )
    path = f"/api/v1/students/{users['alice'].id}/consent"
    assert client.put(path, headers=student, json=body(text_processing=True)).status_code == 409
    response = client.put(
        path, headers=student, json=body(text_processing=True, retention_version=2)
    )
    assert response.status_code == 200
    assert response.json()["disclosure_snapshot"]["retention"]["conversation_days"] == 90


def test_cached_receipt_does_not_override_current_withdrawal(api):
    from sqlalchemy import update

    db, user = api[1], api[2]["alice"]
    receipt = record_consent(db, user.id, POLICY_VERSION, text_processing=True)
    db.flush()
    db.execute(
        update(ConsentRecord)
        .where(ConsentRecord.id == receipt.id)
        .values(withdrawn_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    assert receipt.withdrawn_at is None  # Simulate a long-lived worker identity map.
    with pytest.raises(ConsentDenied):
        job(api)
