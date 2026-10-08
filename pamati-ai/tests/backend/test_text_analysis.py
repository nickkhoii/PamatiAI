from unittest.mock import patch

import pytest
from ai.text.baseline import LexiconBaseline
from ai.text.interface import ModelMetadata, ModelOutput
from ai.text.normalization import normalize
from ai.text.preprocessing import preprocess
from ai.text.registry import ModelRegistry, registry
from ai.text.service import InferenceService
from sqlalchemy import func, select
from test_auth import headers
from test_conversation import api as conversation_api
from test_conversation import fixture_api, send  # noqa: F401 -- shared fixture

from app.config import Settings
from app.consent_policy import POLICY_VERSION, policy_document
from app.models import ModelInference, TextAnalysis
from app.persistence import record_consent, withdraw_consent

api = conversation_api


def test_preprocessing_preserves_research_features():
    assert preprocess("  Hindi ako HAPPY! 😢 cafe\u0301  ").text == "Hindi ako HAPPY! 😢 café"
    with pytest.raises(ValueError):
        preprocess("bad\x00input")


def test_baseline_abstention_and_missing_capabilities():
    service = InferenceService(LexiconBaseline())
    for text in ("", "hello", "masaya ako"):
        result = service.analyze_text(text)
        assert result.abstained and result.labels["sentiment_polarity"] is None
    result = service.analyze_text("happy but sad")
    assert result.labels["sentiment_category"] == "mixed"
    assert result.labels["sentiment_polarity"] == 0
    assert result.confidence is None and result.labels["emotion_probabilities"] is None


@pytest.mark.parametrize("output", [
    ModelOutput(polarity=float("nan")), ModelOutput(polarity=2),
    ModelOutput(confidence=float("inf")), ModelOutput(confidence=True),
    ModelOutput(category="depression"),
    ModelOutput(sentiment_probabilities={"positive": .8, "negative": .8}),
    ModelOutput(emotion_probabilities={"joy": .5}),
    ModelOutput(confidence=.9),
])
def test_invalid_model_output_rejected(output):
    with pytest.raises(ValueError):
        normalize(output)


def test_uncertainty_emotions_and_threshold():
    result = normalize(ModelOutput(
        polarity=.1, category="positive",
        sentiment_probabilities={"positive": .5, "negative": .5},
        emotion_probabilities={"joy": .8, "sadness": .7},
        emotion_probability_kind="independent", confidence=.5,
        confidence_method="uncalibrated_softmax",
    ), minimum_confidence=.6)
    assert result.abstained
    assert result.uncertainty["normalized_entropy"] == pytest.approx(1)
    assert result.labels["emotion_probabilities"]["joy"] == .8
    assert not result.uncertainty["calibrated"]


def test_registry_replacement_and_duplicate_rejection():
    models = ModelRegistry()
    models.register("baseline", LexiconBaseline)
    assert models.resolve("baseline").metadata.version == "1"
    with pytest.raises(ValueError):
        models.register("baseline", LexiconBaseline)
    with pytest.raises(ValueError):
        models.resolve("unknown")


def enable(api, names):
    settings = Settings(text_analysis_models=names)
    context = patch("app.config.get_settings", return_value=settings)
    context.start()
    db, users = api[1], api[2]
    record_consent(db, users["alice"].id, POLICY_VERSION,
                   disclosure_snapshot=policy_document(), text_processing=True)
    db.commit()
    return context


def analysis_path(api, message_id):
    return f"/api/v1/conversations/{api[3]['alice'].id}/messages/{message_id}/analyses"


def test_conversation_persistence_traceability_idempotency_and_access(api):
    context = enable(api, ["lexicon-baseline"])
    try:
        from uuid import uuid4
        request_id = str(uuid4())
        response = send(api, text="I am happy", request_id=request_id)
        assert response.status_code == 200, response.text
        message_id = response.json()["messages"][0]["id"]
        client, db = api[:2]
        path = analysis_path(api, message_id)
        data = client.get(path, headers=headers(api, "alice")).json()["analyses"]
        assert len(data) == 1
        row = data[0]
        assert row["message_id"] == message_id and row["model_version"] == "1"
        assert row["model_id"] and row["analysis_id"] and row["consent_record_id"]
        assert row["completed_at"] and row["started_at"] and row["created_at"]
        assert row["result"]["sentiment_polarity"] == 1
        assert row["status"] == "completed" and row["confidence"] is None
        assert send(api, text="I am happy", request_id=request_id).status_code == 200
        assert db.scalar(select(func.count()).select_from(ModelInference)) == 1
        for name in ("bob", "admin", "other_counselor"):
            assert client.get(path, headers=headers(api, name)).status_code == 403
    finally:
        context.stop()


@pytest.mark.parametrize("mode", ["success", "failure", "withdraw"])
def test_multiple_models_isolate_failure_and_recheck_consent(api, monkeypatch, mode):
    class Experimental:
        metadata = ModelMetadata("experimental", "revision-2", "adapter-1")

        def predict(self, sample):
            if mode == "failure":
                raise RuntimeError("private message and secret")
            if mode == "withdraw":
                withdraw_consent(api[1], api[2]["alice"].id)
                api[1].commit()
            return ModelOutput(polarity=-.2, category="negative", confidence=.8,
                               confidence_method="uncalibrated_test")

    monkeypatch.setitem(registry._factories, "experimental", Experimental)
    context = enable(api, ["experimental", "lexicon-baseline"])
    try:
        response = send(api, text="happy")
        db = api[1]
        rows = list(db.scalars(select(ModelInference).order_by(ModelInference.created_at)))
        assert len(rows) == 2
        if mode == "withdraw":
            assert response.status_code == 409
            assert all(r.processing_status == "cancelled" for r in rows)
            assert db.scalar(select(func.count()).select_from(TextAnalysis)) == 0
        else:
            assert response.status_code == 200
            assert rows[0].processing_status == ("failed" if mode == "failure" else "completed")
            assert rows[1].processing_status == "completed"
            if mode == "failure":
                assert rows[0].error_code == "adapter_failed"
            else:
                assert rows[0].confidence == .8
                assert rows[0].uncertainty["confidence_method"] == "uncalibrated_test"
    finally:
        context.stop()


def test_changed_analysis_configuration_requires_disclosure(api):
    with patch("app.config.get_settings", return_value=Settings(
        text_analysis_models=["lexicon-baseline"]
    )):
        assert send(api).status_code == 409
    assert api[1].scalar(select(func.count()).select_from(ModelInference)) == 0
