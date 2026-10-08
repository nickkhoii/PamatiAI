from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from ai.multimodal.interface import FusionConfig, ModalityObservation
from ai.multimodal.service import FusionService
from ai.multimodal.strategies import LateFusion, WeightedProbabilityFusion
from sqlalchemy import select
from test_auth import api as shared_api
from test_auth import headers

from app.config import Settings
from app.consent_policy import POLICY_VERSION, policy_document
from app.models import (
    FusionInput,
    InteractionSession,
    ModelInference,
    ModelVersion,
    MultimodalAnalysis,
    utcnow,
)
from app.multimodal_fusion import analyze_fusion
from app.persistence import ConsentDenied, create_inference, record_consent, withdraw_consent
from app.processing import run_analysis

api = shared_api


def observation(modality, **changes):
    output = {"text": {"sentiment_probabilities": {"positive": .7, "negative": .3},
                       "emotion_probabilities": {"joy": .8, "sadness": .2}, "emotion_probability_kind": "exclusive"},
              "audio": {"features": {"energy": .2}, "emotion_probabilities": {"joy": .2, "sadness": .8},
                        "emotion_probability_kind": "exclusive"},
              "visual": {"expression_probabilities": {"smiling": .6, "frowning": .4},
                         "probability_kind": "exclusive"}}[modality]
    return replace(ModalityObservation(modality, str(uuid4()), "completed", output, modality + "-model", "1",
                                      datetime.now(UTC).isoformat()), **changes)


@pytest.mark.parametrize("modalities", [("text",), ("audio",), ("visual",), ("text", "audio"),
                                       ("text", "visual"), ("text", "audio", "visual")])
@pytest.mark.parametrize("strategy", [LateFusion, WeightedProbabilityFusion])
def test_combinations(modalities, strategy):
    result = FusionService(strategy()).fuse([observation(m) for m in modalities])
    assert result.labels["available_modalities"] == list(modalities)
    assert set(result.labels["missing_modalities"]) == {"text", "audio", "visual"} - set(modalities)
    assert result.labels["experimental"] and not result.labels["empirically_validated"]
    assert result.confidence is None and not result.uncertainty["calibrated"]


def test_weights_and_semantics():
    sources = [observation(m) for m in ("text", "audio", "visual")]
    result = FusionService(WeightedProbabilityFusion(), FusionConfig(weights={"text": 3, "audio": 1, "visual": 8})).fuse(sources)
    affect = next(c for c in result.labels["combined_output"]["probability_channels"] if c["target"] == "modeled_affect")
    assert affect["probabilities"]["joy"] == pytest.approx(.65)
    assert affect["effective_weights"] == {sources[0].source_id: .75, sources[1].source_id: .25}
    audio = observation("audio", output={"emotion_probabilities": {"joy": .2}, "emotion_probability_kind": "independent"})
    channels = FusionService(WeightedProbabilityFusion()).fuse([sources[0], audio]).labels["combined_output"]["probability_channels"]
    assert len([c for c in channels if c["target"] == "modeled_affect"]) == 2


@pytest.mark.parametrize("status", ["failed", "pending", "abstained", "cancelled"])
def test_failed_modality(status):
    result = FusionService(LateFusion()).fuse([observation("text"), observation("audio", status=status)])
    assert result.labels["available_modalities"] == ["text"]
    assert result.labels["excluded_modalities"]["audio"] == status


def test_unconsented_empty_and_alignment():
    result = FusionService(LateFusion()).fuse([observation("audio", output=Mock())], consented_modalities=["text"])
    assert result.abstained and not result.source_inference_ids
    assert FusionService(LateFusion()).fuse([]).abstained
    old = observation("audio", timestamp=(datetime.now(UTC) - timedelta(seconds=301)).isoformat())
    assert FusionService(LateFusion()).fuse([observation("text"), old]).labels["excluded_modalities"]["audio"] == "out_of_alignment_window"


@pytest.mark.parametrize("weights", [{"text": -1}, {"text": float("nan")}, {"text": 0}, {"unknown": 1}])
def test_invalid_weights(weights):
    with pytest.raises(ValueError):
        FusionService(LateFusion(), FusionConfig(weights=weights))


def setup(api, monkeypatch, modalities=("text", "audio", "visual")):
    monkeypatch.setattr("app.config.get_settings", lambda: Settings())
    record_consent(api[1], api[2]["alice"].id, POLICY_VERSION, disclosure_snapshot=policy_document(),
                   **{m + "_processing": m in modalities for m in ("text", "audio", "visual")})
    api[1].commit()
    return api[1].scalar(select(InteractionSession.id).where(InteractionSession.student_id == api[2]["alice"].id))


def stored(api, session_id, modality):
    db = api[1]
    model = ModelVersion(model_identifier="test-" + modality, version="1", modality=modality, configuration={})
    db.add(model)
    db.flush()
    row = create_inference(db, student_id=api[2]["alice"].id, session_id=session_id, model_version_id=model.id,
                           preprocessing_version="1", adapter_version="1")
    adapter = Mock()
    adapter.analyze.return_value = SimpleNamespace(labels=observation(modality).output, limitations=[])
    run_analysis(db, row.id, adapter, {modality: row.id})
    return row.id


@pytest.mark.parametrize("modalities", [("text",), ("text", "audio"), ("text", "visual"), ("text", "audio", "visual")])
def test_persistence(api, monkeypatch, modalities):
    session_id = setup(api, monkeypatch)
    ids = [stored(api, session_id, m) for m in modalities]
    response = api[0].post(f"/api/v1/sessions/{session_id}/multimodal-analyses", headers=headers(api, "alice"),
                           json={"source_inference_ids": ids})
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "completed", data
    row = api[1].get(ModelInference, data["analysis_id"], populate_existing=True)
    assert row.input_modalities == list(modalities)
    assert {e.source_inference_id for e in api[1].scalars(select(FusionInput).where(FusionInput.fusion_inference_id == row.id))} == set(ids)
    assert api[0].get(f"/api/v1/multimodal-analyses/{row.id}", headers=headers(api, "bob")).status_code == 403


@pytest.mark.parametrize("change", ["withdraw", "delete", "configuration"])
def test_publication_recheck(api, monkeypatch, change):
    session_id = setup(api, monkeypatch)
    source = stored(api, session_id, "text")
    original = LateFusion.fuse
    def changing(self, observations, config):
        running = api[1].scalar(select(ModelInference).where(ModelInference.modality == "multimodal",
                                                            ModelInference.processing_status == "running"))
        if running:
            if change == "withdraw":
                withdraw_consent(api[1], api[2]["alice"].id)
            elif change == "delete":
                api[1].get(ModelInference, source).deleted_at = utcnow()
            else:
                monkeypatch.setattr("app.config.get_settings", lambda: Settings(multimodal_fusion_enabled=False))
            api[1].commit()
        return original(self, observations, config)
    monkeypatch.setattr(LateFusion, "fuse", changing)
    identifier = analyze_fusion(api[1], session_id=session_id, student_id=api[2]["alice"].id, source_inference_ids=[source])
    assert api[1].get(MultimodalAnalysis, identifier) is None
    assert api[1].get(ModelInference, identifier).processing_status == "cancelled"


def test_unconsented_and_missing_source(api, monkeypatch):
    session_id = setup(api, monkeypatch)
    text, audio = stored(api, session_id, "text"), stored(api, session_id, "audio")
    setup(api, monkeypatch, ("text",))
    identifier = analyze_fusion(api[1], session_id=session_id, student_id=api[2]["alice"].id,
                                source_inference_ids=[text, audio, str(uuid4())])
    labels = api[1].get(MultimodalAnalysis, identifier).labels
    assert labels["available_modalities"] == ["text"]
    assert labels["excluded_modalities"]["audio"] == "unconsented"
    with pytest.raises(ConsentDenied):
        analyze_fusion(api[1], session_id=session_id, student_id=api[2]["alice"].id, source_inference_ids=[audio])


def test_learned_interface_and_provenance_guard():
    from ai.multimodal.interface import FusionMetadata, FusionOutput, ProbabilityChannel
    from ai.multimodal.registry import FusionRegistry

    source = observation("visual")
    class Learned:
        metadata = FusionMetadata("learned", "1", learned=True, artifact_sha256="a" * 64)
        def fuse(self, observations, config):
            return FusionOutput((ProbabilityChannel("modeled_affect", "exclusive", {"joy": 1}, (source.source_id,)),))
    registry = FusionRegistry()
    registry.register("learned", Learned)
    with pytest.raises(ValueError, match="target"):
        FusionService(registry.resolve("learned")).fuse([source])
    Learned.metadata = replace(Learned.metadata, artifact_sha256=None)
    with pytest.raises(ValueError, match="SHA-256"):
        registry.resolve("learned")


def test_learned_confidence_and_missing_inputs():
    from ai.multimodal.interface import FusionMetadata, FusionOutput, ProbabilityChannel

    class Learned:
        metadata = FusionMetadata("example", "1", learned=True, artifact_sha256="b" * 64)
        def fuse(self, observations, config):
            assert len(observations) == 1
            return FusionOutput((ProbabilityChannel("text_sentiment", "exclusive", {"positive": .6, "negative": .4},
                                                     (observations[0].source_id,)),),
                                confidence=.4, confidence_method="uncalibrated_example_score")
    result = FusionService(Learned(), FusionConfig(minimum_confidence=.5)).fuse([observation("text")])
    assert result.abstained and result.confidence == .4
    assert not result.uncertainty["calibrated"]


def test_failed_source_persistence(api, monkeypatch):
    session_id = setup(api, monkeypatch)
    text = stored(api, session_id, "text")
    model = ModelVersion(model_identifier="failed-audio", version="1", modality="audio", configuration={})
    api[1].add(model)
    api[1].flush()
    audio = create_inference(api[1], student_id=api[2]["alice"].id, session_id=session_id,
                             model_version_id=model.id, preprocessing_version="1", adapter_version="1")
    adapter = Mock()
    adapter.analyze.side_effect = RuntimeError("model unavailable")
    run_analysis(api[1], audio.id, adapter, {"audio": audio.id})
    identifier = analyze_fusion(api[1], session_id=session_id, student_id=api[2]["alice"].id,
                                source_inference_ids=[text, audio.id])
    labels = api[1].get(MultimodalAnalysis, identifier).labels
    assert labels["available_modalities"] == ["text"]
    assert labels["excluded_modalities"]["audio"] == "failed"


def test_strategy_failure_no_result(api, monkeypatch):
    session_id = setup(api, monkeypatch)
    text = stored(api, session_id, "text")
    from ai.multimodal.strategies import WeightedProbabilityFusion
    monkeypatch.setattr("app.config.get_settings", lambda: Settings(multimodal_fusion_strategy="weighted-probability"))
    record_consent(api[1], api[2]["alice"].id, POLICY_VERSION, disclosure_snapshot=policy_document(), text_processing=True)
    api[1].commit()
    monkeypatch.setattr(WeightedProbabilityFusion, "fuse", Mock(side_effect=RuntimeError("failed")))
    identifier = analyze_fusion(api[1], session_id=session_id, student_id=api[2]["alice"].id,
                                source_inference_ids=[text])
    assert api[1].get(ModelInference, identifier).processing_status == "failed"
    assert api[1].get(MultimodalAnalysis, identifier) is None
