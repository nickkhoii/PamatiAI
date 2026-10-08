from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select
from test_auth import api as shared_api
from test_auth import headers

from app.config import Settings
from app.consent_policy import POLICY_VERSION, policy_document
from app.longitudinal import rebuild, summaries
from app.models import (
    InteractionSession,
    ModelInference,
    ModelVersion,
    SentimentObservation,
    SentimentTrend,
    TrendObservation,
    utcnow,
)
from app.persistence import ConsentDenied, create_inference, record_consent, withdraw_consent
from app.processing import run_analysis

api = shared_api


def configure(api, monkeypatch, *, tracking=True, text=True):
    settings = Settings(longitudinal_configuration={"minimum_baseline_interactions": 4, "minimum_baseline_days": 4})
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    record_consent(api[1], api[2]["alice"].id, POLICY_VERSION, disclosure_snapshot=policy_document(),
                   text_processing=text, longitudinal_tracking=tracking, reviewer_access=True)
    api[1].commit()


def window():
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return end - timedelta(days=10), end


def source(api, day, score=.3, version="1", preprocessing="1"):
    db, student = api[1], api[2]["alice"].id
    model = db.scalar(select(ModelVersion).where(ModelVersion.model_identifier == "synthetic-text",
                                                ModelVersion.version == version))
    if not model:
        model = ModelVersion(model_identifier="synthetic-text", version=version, modality="text", configuration={})
        db.add(model)
        db.flush()
    previous = db.scalar(select(InteractionSession).where(InteractionSession.student_id == student))
    interaction = InteractionSession(student_id=student, conversation_id=previous.conversation_id,
                                      created_at=day.replace(tzinfo=None))
    db.add(interaction)
    db.flush()
    row = create_inference(db, student_id=student, session_id=interaction.id, model_version_id=model.id,
                           preprocessing_version=preprocessing, adapter_version="1")
    row.created_at = (day + timedelta(hours=1)).replace(tzinfo=None)
    db.flush()
    adapter = Mock()
    adapter.analyze.return_value = SimpleNamespace(
        labels={"sentiment_polarity": score, "emotion_probabilities": {"joy": .5, "sadness": .5},
                "emotion_probability_kind": "exclusive", "abstained": False}, limitations=[], confidence=.8,
        uncertainty={"method": "unavailable", "calibrated": False}, uncertainty_method="unavailable", language="en", abstained=False,
    )
    run_analysis(db, row.id, adapter, {"text": row.id})
    return row.id


def generate(api, start, end):
    return api[0].post(f"/api/v1/students/{api[2]['alice'].id}/longitudinal", headers=headers(api, "alice"),
                       json={"start": start.date().isoformat(), "end": end.date().isoformat()})


def test_persistence_and_roles(api, monkeypatch):
    configure(api, monkeypatch)
    start, end = window()
    for i in range(8):
        source(api, start + timedelta(days=i))
    response = generate(api, start, end)
    assert response.status_code == 201, response.text
    series = response.json()["series"]
    polarity = next(s for s in series if s["dimension"] == "sentiment_polarity")
    assert polarity["summary"]["daily"][7]["baseline"]["mean"] == pytest.approx(.3)
    assert polarity["summary"]["daily"][9]["mean"] is None
    assert len(polarity["summary"]["interactions"]) == 8
    assert api[1].scalar(select(func.count()).select_from(TrendObservation)) == 24
    for name, status in (("alice", 200), ("counselor", 200), ("bob", 403), ("other_counselor", 403), ("admin", 403)):
        response = api[0].get(f"/api/v1/students/{api[2]['alice'].id}/longitudinal", headers=headers(api, name))
        assert response.status_code == status, (name, response.text)
    before = api[1].scalar(select(func.count()).select_from(SentimentObservation))
    assert generate(api, start, end).status_code == 201
    assert api[1].scalar(select(func.count()).select_from(SentimentObservation)) == before
    assert len(summaries(api[1], api[2]["alice"].id)) == 3


def test_consent_and_retrospective_use(api, monkeypatch):
    configure(api, monkeypatch, tracking=False)
    start, end = window()
    source(api, start)
    assert generate(api, start, end).status_code == 409
    assert not list(api[1].scalars(select(SentimentObservation)))
    configure(api, monkeypatch)
    assert generate(api, start, end).json()["series"] == []
    source(api, start + timedelta(days=1))
    assert generate(api, start, end).json()["series"]
    withdraw_consent(api[1], api[2]["alice"].id)
    api[1].commit()
    assert not summaries(api[1], api[2]["alice"].id)


def test_versions_not_pooled(api, monkeypatch):
    configure(api, monkeypatch)
    start, end = window()
    for i in range(4):
        source(api, start + timedelta(days=i), .9)
    source(api, start + timedelta(days=5), -.8, version="2")
    source(api, start + timedelta(days=6), -.6, preprocessing="2")
    response = generate(api, start, end)
    assert response.status_code == 201, response.text
    polarity = [s for s in response.json()["series"] if s["dimension"] == "sentiment_polarity"]
    assert len(polarity) == 3
    assert next(s for s in polarity if s["model_version"] == "2")["summary"]["daily"][5]["baseline"]["mean"] is None


def test_deleted_or_unconsented_sources_hide_snapshot(api, monkeypatch):
    configure(api, monkeypatch)
    start, end = window()
    identifier = source(api, start)
    assert generate(api, start, end).json()["series"]
    api[1].get(ModelInference, identifier).deleted_at = utcnow()
    api[1].commit()
    assert not summaries(api[1], api[2]["alice"].id)


def test_baseline_evidence_precedes_display_window(api, monkeypatch):
    configure(api, monkeypatch)
    start, end = window()
    for i in range(5):
        source(api, start - timedelta(days=i + 1), .4)
    source(api, start, -.6)
    response = generate(api, start, end)
    assert response.status_code == 201, response.text
    polarity = next(s for s in response.json()["series"] if s["dimension"] == "sentiment_polarity")
    assert polarity["summary"]["daily"][0]["baseline"]["mean"] == pytest.approx(.4)
    trend = api[1].get(SentimentTrend, polarity["id"])
    assert trend.window_start < start.replace(tzinfo=None)
    assert trend.sample_count == 6


def test_changed_disclosure(api, monkeypatch):
    configure(api, monkeypatch)
    start, end = window()
    source(api, start)
    monkeypatch.setattr("app.config.get_settings", lambda: Settings(longitudinal_configuration={"change_threshold": .5}))
    assert generate(api, start, end).status_code == 409


def test_source_changes_discard_generation(api, monkeypatch):
    from ai.longitudinal.algorithms import DescriptiveTracking
    configure(api, monkeypatch)
    start, end = window()
    identifier = source(api, start)
    original = DescriptiveTracking.summarize
    def changing(self, *args, **kwargs):
        api[1].get(ModelInference, identifier).deleted_at = utcnow()
        api[1].flush()
        return original(self, *args, **kwargs)
    monkeypatch.setattr(DescriptiveTracking, "summarize", changing)
    with pytest.raises(ConsentDenied):
        rebuild(api[1], api[2]["alice"].id, start, end)
    api[1].rollback()
    assert not list(api[1].scalars(select(SentimentTrend)))
