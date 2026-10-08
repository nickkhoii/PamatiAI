from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from test_auth import api as shared_api
from test_auth import headers as login_headers
from test_conversation import send

from app.config import Settings
from app.consent_policy import POLICY_VERSION, policy_document
from app.models import AuditLog, HumanReview, Message, ReviewerAssignment, RiskSignal, utcnow
from app.persistence import record_consent, withdraw_consent
from services.safety.policy import LiteralSafetyAnalyzer, SafetyCandidate, SafetyPolicy, evaluate
from services.safety.resources import SafetyResource, supportive_message

api = shared_api


def headers(api, name):
    cache = api[1].info.setdefault("safety_test_headers", {})
    if name not in cache:
        cache[name] = login_headers(api, name)
    return cache[name]


def configure(api, monkeypatch, *, text=True, reviewer=True, resources=(), policy=None, models=()):
    settings = Settings(safety_policy=policy or {}, safety_resources=list(resources), text_analysis_models=list(models))
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    for name in ("alice", "bob"):
        record_consent(api[1], api[2][name].id, POLICY_VERSION, disclosure_snapshot=policy_document(),
                       text_processing=text, reviewer_access=reviewer)
    api[1].commit()
    return settings


def signal(api):
    return api[1].scalar(select(RiskSignal).order_by(RiskSignal.created_at.desc()))


@pytest.mark.parametrize("text", ["I want to kill myself", "I AM GOING TO KILL MYSELF", "I want to die!",
                                 "I might hurt myself", "Someone is attacking me", "I cannot keep myself safe",
                                 "I have taken an overdose", "I\nwant\tto die", "i\u2019m going to hurt myself"])
def test_explicit_language_matches_without_sentiment(text):
    policy = SafetyPolicy()
    result = evaluate(LiteralSafetyAnalyzer().analyze(text, policy), policy)
    assert result and any(r.priority == "urgent" for r in result)
    assert all(r.confidence is None for r in result)


@pytest.mark.parametrize("text", ["I am sad", "I hate these exams", "I feel negative and stressed", "I am depressed",
                                 "I do not want to kill myself", "I don't want to die", "kill process", "dying my hair",
                                 "My sentiment score is -1", "Depressed Student", "", "i want to diet"])
def test_negative_or_unrelated_language_is_not_urgent(text):
    assert not LiteralSafetyAnalyzer().analyze(text, SafetyPolicy())


def test_unknown_diagnostic_candidate_does_not_route():
    assert not evaluate([SafetyCandidate("model", "mental_disorder", "urgent", 1)], SafetyPolicy())
    with pytest.raises(ValidationError):
        SafetyPolicy(rules=[{"id": "bad", "category": "depressed_student", "priority": "urgent", "phrases": ["sad student"]}])


def test_configurable_language_rules():
    policy = SafetyPolicy(version="institution-2", rules=[{"id": "approved-language", "category": "immediate_danger",
                            "priority": "urgent", "phrases": ["example danger phrase"]}])
    assert LiteralSafetyAnalyzer().analyze("Example danger phrase", policy)
    assert not LiteralSafetyAnalyzer().analyze("i want to die", policy)
    assert policy.fingerprint != SafetyPolicy().fingerprint


@pytest.mark.parametrize("url", ["http://example.test", "javascript:alert(1)", "https://user:secret@example.test"])
def test_resource_links_safe(url):
    with pytest.raises(ValidationError):
        SafetyResource(id="example", label="Support", kind="campus", institution="Test", jurisdiction="Test", url=url)


def test_generic_resources_no_fabricated_number():
    text = supportive_message("urgent", ())
    assert "local emergency" in text and "trusted person" in text
    assert "not automatically contacted" in text
    assert "911" not in text and "988" not in text


def test_immediate_support_bypasses_provider_and_models(api, monkeypatch):
    configure(api, monkeypatch, models=("lexicon-baseline",))
    with patch("app.conversation_routes.safe_reply") as provider, patch("app.conversation_routes.execute") as execute:
        response = send(api, text="I want to kill myself")
    assert response.status_code == 200, response.text
    provider.assert_not_called()
    execute.assert_not_called()
    answer = response.json()["messages"][-1]
    assert answer["generation"]["provider"] == "local-safety"
    assert "do not wait" in answer["text"].lower()
    row = signal(api)
    assert row.workflow_state == "new" and row.source_message_id == response.json()["messages"][0]["id"]
    assert row.signal_code == "self_harm_language" and row.confidence is None
    assert row.consent_record_id and len(row.rule_version) == 64
    assert "I want to kill myself" not in str(row.explanation)


def test_negative_model_estimate_never_creates_urgent_signal(api, monkeypatch):
    configure(api, monkeypatch, models=("lexicon-baseline",))
    response = send(api, text="I am sad and angry and disappointed")
    assert response.status_code == 200
    assert signal(api) is None
    assert response.json()["messages"][-1]["generation"]["provider"] != "local-safety"


def test_safety_replay_idempotent(api, monkeypatch):
    configure(api, monkeypatch)
    request = str(uuid4())
    first = send(api, text="I want to die", request_id=request)
    second = send(api, text="I want to die", request_id=request)
    assert first.json() == second.json()
    assert len(list(api[1].scalars(select(RiskSignal)))) == 1


def test_urgent_does_not_wait_for_pending_turn(api, monkeypatch):
    configure(api, monkeypatch)
    session = api[1].scalar(select(Message.session_id).where(Message.student_id == api[2]["alice"].id))
    pending = Message(student_id=api[2]["alice"].id, session_id=session, sender="assistant", sequence_number=1,
                      generation={"status": "pending"})
    api[1].add(pending)
    api[1].commit()
    response = send(api, text="Someone is attacking me")
    assert response.status_code == 200, response.text
    assert api[1].get(Message, pending.id, populate_existing=True).generation["status"] == "fallback"


def test_no_processing_without_text_consent(api, monkeypatch):
    configure(api, monkeypatch, text=False)
    with patch("app.conversation_routes.screen") as screen:
        assert send(api, text="I want to die").status_code == 409
        screen.assert_not_called()
    assert not signal(api)
    assert api[0].get("/api/v1/safety/resources").status_code == 200


RESOURCE = {"id": "campus-support", "label": "Institution support", "kind": "campus", "institution": "Test institution",
            "jurisdiction": "Test jurisdiction", "url": "https://support.example.test", "availability": "Confirm availability"}


def test_institution_resources_and_updates(api, monkeypatch):
    configure(api, monkeypatch, resources=(RESOURCE,))
    response = send(api, text="I want to die")
    assert "https://support.example.test" in response.json()["messages"][-1]["text"]
    settings = Settings(safety_resources=[{**RESOURCE, "url": "https://updated.example.test"}])
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    assert send(api, text="I want to die").status_code == 200


def queue(api, name="counselor", state="new"):
    return api[0].get(f"/api/v1/reviewer/safety-queue?state={state}", headers=headers(api, name))


def action(api, row, decision, *, actor="counselor", revision=None, notes="Context reviewed and follow-up documented"):
    return api[0].post(f"/api/v1/safety-signals/{row.id}/reviews", headers=headers(api, actor),
                       json={"decision": decision, "expected_revision": revision or row.revision, "notes": notes})


def test_review_states_audit_and_referral(api, monkeypatch):
    configure(api, monkeypatch, resources=(RESOURCE,))
    send(api, text="I want to die")
    row = signal(api)
    assert queue(api).json()["items"][0]["human_review_status"] == "not_started"
    assert action(api, row, "acknowledge").status_code == 201
    assert row.workflow_state == "under_review"
    assert queue(api, state="under_review").json()["items"]
    review = action(api, row, "refer")
    assert review.status_code == 201, review.text
    response = api[0].post(f"/api/v1/students/{row.student_id}/referrals", headers=headers(api, "counselor"),
                           json={"human_review_id": review.json()["id"], "service_reference": RESOURCE["id"]})
    assert response.status_code == 201, response.text
    assert row.workflow_state == "referred"
    assert queue(api, state="referred").json()["items"]
    assert action(api, row, "resolve").status_code == 409
    assert action(api, row, "reopen").status_code == 201
    assert action(api, row, "resolve").status_code == 201
    assert row.workflow_state == "resolved"
    audits = list(api[1].scalars(select(AuditLog).where(AuditLog.action.like("review.%"))))
    assert {a.action for a in audits} >= {"review.acknowledge", "review.refer", "review.reopen", "review.resolve"}
    assert all("Context reviewed" not in str(a.__dict__) for a in audits)


@pytest.mark.parametrize("actor", ["alice", "bob", "admin", "other_counselor"])
def test_queue_and_actions_authorization(api, monkeypatch, actor):
    configure(api, monkeypatch)
    send(api, text="I want to die")
    row = signal(api)
    response = queue(api, actor)
    if actor == "other_counselor":
        assert response.status_code == 200 and not response.json()["items"]
    else:
        assert response.status_code == 403
    assert action(api, row, "acknowledge", actor=actor).status_code == 403


@pytest.mark.parametrize("change", ["reviewer_consent", "withdrawal", "assignment", "deleted_source"])
def test_queue_rechecks_permission_and_source(api, monkeypatch, change):
    configure(api, monkeypatch)
    send(api, text="I want to die")
    row = signal(api)
    if change == "reviewer_consent":
        configure(api, monkeypatch, reviewer=False)
    elif change == "withdrawal":
        withdraw_consent(api[1], row.student_id)
    elif change == "assignment":
        assignment = api[1].scalar(select(ReviewerAssignment).where(ReviewerAssignment.student_id == row.student_id))
        assignment.revoked_at = utcnow()
    else:
        api[1].get(Message, row.source_message_id).deleted_at = utcnow()
    api[1].commit()
    assert not queue(api).json()["items"]
    assert action(api, row, "acknowledge").status_code in {403, 404}


def test_review_notes_revision_and_claim_conflicts(api, monkeypatch):
    configure(api, monkeypatch)
    send(api, text="I want to die")
    row = signal(api)
    assert action(api, row, "acknowledge", notes="").status_code == 422
    assert action(api, row, "acknowledge").status_code == 201
    assert action(api, row, "resolve", revision=1).status_code == 409
    api[1].add(ReviewerAssignment(student_id=row.student_id, reviewer_id=api[2]["other_counselor"].id,
                                   assigned_by=api[2]["admin"].id))
    api[1].commit()
    assert action(api, row, "resolve", actor="other_counselor").status_code == 409


def test_student_referral_choice_no_automatic_acceptance(api, monkeypatch):
    configure(api, monkeypatch, resources=(RESOURCE,))
    send(api, text="I want to die")
    row = signal(api)
    review = action(api, row, "refer").json()
    referral = api[0].post(f"/api/v1/students/{row.student_id}/referrals", headers=headers(api, "counselor"),
                           json={"human_review_id": review["id"], "service_reference": RESOURCE["id"]}).json()
    path = f"/api/v1/students/{row.student_id}/safety-follow-ups/{referral['id']}"
    assert api[0].patch(f"/api/v1/referrals/{referral['id']}", headers=headers(api, "counselor"), json={"status": "accepted"}).status_code == 422
    assert api[0].patch(path, headers=headers(api, "alice"), json={"status": "accepted"}).status_code == 200
    assert api[0].patch(path, headers=headers(api, "bob"), json={"status": "declined"}).status_code == 403
    assert api[0].get(f"/api/v1/students/{row.student_id}/safety-follow-ups", headers=headers(api, "alice")).json()[0]["automatic_contact"] is False


def test_safety_migration_offline_names_and_evidence_guard():
    from io import StringIO
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    output = StringIO()
    config = Config(str(Path(__file__).resolve().parents[2] / "backend" / "alembic.ini"), output_buffer=output)
    command.upgrade(config, "0007_conversation:head", sql=True)
    sql = output.getvalue()
    assert "ck_risk_signals_ck_" not in sql and "ck_human_reviews_ck_" not in sql
    assert "DROP CHECK ck_risk_signals_signal_source" in sql
    assert "safety_message_source_guard" in sql and "safety_provenance_guard" in sql
    assert "'resolve'" in sql and "'reopen'" in sql


def test_quoted_content_routes_to_context_review_not_diagnosis(api, monkeypatch):
    configure(api, monkeypatch)
    response = send(api, text='The story quotes "I want to die". We are discussing literature.')
    assert response.status_code == 200
    assert signal(api).signal_code == "self_harm_language"
    assert "not_diagnosis" in signal(api).explanation["interpretation"]
    assert action(api, signal(api), "dismiss", notes="Quotation in literature; context reviewed").status_code == 201


def test_rules_changed_require_disclosure_acknowledgment(api, monkeypatch):
    configure(api, monkeypatch)
    monkeypatch.setattr("app.config.get_settings", lambda: Settings(safety_policy={"version": "new-rule-version"}))
    assert send(api, text="I want to die").status_code == 409
    assert signal(api) is None


def test_unknown_referral_service_not_published(api, monkeypatch):
    configure(api, monkeypatch)
    send(api, text="I want to die")
    row = signal(api)
    review = action(api, row, "refer")
    response = api[0].post(f"/api/v1/students/{row.student_id}/referrals", headers=headers(api, "counselor"),
                           json={"human_review_id": review.json()["id"], "service_reference": "unverified-service"})
    assert response.status_code == 422
    assert row.workflow_state == "under_review"


def test_stale_referral_proposal_cannot_create_offer(api, monkeypatch):
    configure(api, monkeypatch, resources=(RESOURCE,))
    send(api, text="I want to die")
    row = signal(api)
    proposal = action(api, row, "refer")
    assert action(api, row, "follow_up").status_code == 201
    response = api[0].post(f"/api/v1/students/{row.student_id}/referrals", headers=headers(api, "counselor"),
                           json={"human_review_id": proposal.json()["id"], "service_reference": RESOURCE["id"]})
    assert response.status_code == 409


def test_native_offer_closure_requires_documented_followup(api, monkeypatch):
    configure(api, monkeypatch, resources=(RESOURCE,))
    send(api, text="I want to die")
    row = signal(api)
    review = action(api, row, "refer")
    offer = api[0].post(f"/api/v1/students/{row.student_id}/referrals", headers=headers(api, "counselor"),
                        json={"human_review_id": review.json()["id"], "service_reference": RESOURCE["id"]}).json()
    path = f"/api/v1/referrals/{offer['id']}"
    assert api[0].patch(path, headers=headers(api, "counselor"), json={"status": "closed"}).status_code == 422
    assert api[0].patch(path, headers=headers(api, "counselor"), json={"status": "closed", "notes": "Context and follow-up outcome documented"}).status_code == 200
    assert api[1].scalar(select(HumanReview).where(HumanReview.notes == "Context and follow-up outcome documented"))
    student_path = f"/api/v1/students/{row.student_id}/safety-follow-ups/{offer['id']}"
    assert api[0].patch(student_path, headers=headers(api, "alice"), json={"status": "accepted"}).status_code == 409


def test_support_without_reviewer_access_has_no_false_notification_claim(api, monkeypatch):
    configure(api, monkeypatch, reviewer=False)
    response = send(api, text="I am in immediate danger")
    assert response.status_code == 200
    assert "not automatically contacted anyone" in response.json()["messages"][-1]["text"]
    assert signal(api) is not None and not queue(api).json()["items"]
    from app.models import Notification
    assert not list(api[1].scalars(select(Notification)))


def test_prompt_and_multiple_reason_categories(api, monkeypatch):
    configure(api, monkeypatch)
    response = send(api, text="I do not feel safe")
    assert response.json()["messages"][-1]["generation"]["safety_priority"] == "prompt"
    response = send(api, text="I want to die and someone is attacking me")
    source_id = response.json()["messages"][0]["id"]
    rows = list(api[1].scalars(select(RiskSignal).where(RiskSignal.source_message_id == source_id)))
    assert {r.signal_code for r in rows} == {"self_harm_language", "immediate_danger"}
    assert all(r.priority == "urgent" for r in rows)


@pytest.mark.parametrize("label", ["Depressed Student", "Suicidal Student", "Mental Disorder Detected"])
def test_diagnostic_provider_labels_are_replaced(label):
    from services.conversation.providers import Reply, safe_reply
    provider = Mock()
    provider.generate.return_value = Reply(label, "mock", "mock", "1")
    with patch("services.conversation.providers.get_provider", return_value=provider):
        assert safe_reply([{"role": "user", "content": "hello"}]).fallback
