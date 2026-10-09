import asyncio
import base64
import json
import struct
from dataclasses import replace
from unittest.mock import Mock

import pytest
from ai.visual.features import NoExpressionExtractor, frame_quality
from ai.visual.interface import ObservableFeatures, VisualMetadata, VisualModelOutput
from ai.visual.normalization import normalize, normalize_features
from ai.visual.registry import NoExpressionModel, VisualRegistry, extractors, models
from ai.visual.sampling import sample_frames
from ai.visual.service import VisualInferenceService
from ai.visual.validation import EncodedFrame, InvalidVisualInput, decode_frame, validate_frames
from fastapi import HTTPException, Request
from sqlalchemy import func, select
from test_auth import api as shared_api
from test_auth import headers
from test_conversation import send

from app.config import Settings
from app.consent_policy import POLICY_VERSION, policy_document
from app.models import InteractionSession, MediaAsset, ModelInference, VisualAnalysis
from app.persistence import ConsentDenied, record_consent, withdraw_consent
from app.visual_analysis import analyze_visual
from app.visual_routes import parse_frames, upload_visual

api = shared_api


def bmp_bytes(width=4, height=4, rgb=(120, 120, 120), *, top_down=False):
    stride = ((width * 3 + 3) // 4) * 4
    pixels = bytes(rgb[::-1]) * width + b"\x00" * (stride - width * 3)
    payload = pixels * height
    return (b"BM" + struct.pack("<IHHI", 54 + len(payload), 0, 0, 54)
            + struct.pack("<IiiHHIIiiII", 40, width, -height if top_down else height, 1, 24,
                          0, len(payload), 0, 0, 0, 0) + payload)


def configure(api, monkeypatch, tmp_path, *, visual=True, enabled=True,
              extractor="no-expression", model="no-expression", retain=False):
    settings = Settings(
        visual_analysis_enabled=enabled, visual_feature_extractor=extractor,
        visual_analysis_model=model, visual_temporary_directory=str(tmp_path / "temporary"),
        allow_raw_media_storage=retain,
    )
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    receipt = record_consent(
        api[1], api[2]["alice"].id, POLICY_VERSION, disclosure_snapshot=policy_document(),
        text_processing=True, visual_processing=visual, retain_visual=retain,
    )
    api[1].commit()
    return settings, receipt


def session_id(api, name="alice"):
    return api[1].scalar(select(InteractionSession.id).where(
        InteractionSession.student_id == api[2][name].id,
    ))


def analyze(api, frames=None):
    return analyze_visual(api[1], session_id=session_id(api), student_id=api[2]["alice"].id,
                          frames=frames if frames is not None else (EncodedFrame(bmp_bytes()),))


def upload(api, *, data=None, content_type="image/bmp", name="alice", target="alice"):
    return api[0].post(
        f"/api/v1/sessions/{session_id(api, target)}/visual-analyses",
        headers={**headers(api, name), "Content-Type": content_type},
        content=bmp_bytes() if data is None else data,
    )


def frame_envelope(count=10):
    return json.dumps({"frames": [
        {"bmp_base64": base64.b64encode(bmp_bytes(rgb=(i * 10, 100, 100))).decode(),
         "timestamp_seconds": float(i)} for i in range(count)
    ]}).encode()


@pytest.mark.parametrize("top_down", [False, True])
def test_decode_known_bmp_pixels_and_quality(top_down):
    encoded = EncodedFrame(bmp_bytes(width=3, rgb=(255, 0, 0), top_down=top_down))
    frames = validate_frames([encoded])
    frame = decode_frame(frames[0])
    assert (frame.width, frame.height) == (3, 4)
    assert frame.rgb == b"\xff\x00\x00" * 12
    quality = frame_quality((frame,))
    assert quality["mean_frame_luminance"] == pytest.approx(.299)
    assert quality["mean_frame_luminance_std"] == 0
    assert quality["face_presence"] == "not_established"


def test_bottom_up_rows_are_decoded_in_image_order():
    data = bytearray(bmp_bytes(width=1, height=2))
    data[54:57] = b"\xff\x00\x00"  # Blue bottom row.
    data[58:61] = b"\x00\x00\xff"  # Red top row.
    assert decode_frame(EncodedFrame(bytes(data))).rgb == b"\xff\x00\x00\x00\x00\xff"


@pytest.mark.parametrize("kind", ["empty", "signature", "truncated", "compressed", "size", "pixels", "planes", "depth"])
def test_invalid_media_rejected(kind):
    data = bytearray(bmp_bytes())
    if kind == "empty":
        data = bytearray()
    elif kind == "signature":
        data[:2] = b"PK"
    elif kind == "truncated":
        data.pop()
    elif kind == "compressed":
        struct.pack_into("<I", data, 30, 1)
    elif kind == "size":
        struct.pack_into("<I", data, 2, 999)
    elif kind == "pixels":
        struct.pack_into("<i", data, 18, 100000)
    elif kind == "planes":
        struct.pack_into("<H", data, 26, 2)
    else:
        struct.pack_into("<H", data, 28, 32)
    with pytest.raises(InvalidVisualInput):
        validate_frames((EncodedFrame(bytes(data)),))


@pytest.mark.parametrize("time", [-1, float("nan"), float("inf"), True, 31, "0"])
def test_invalid_frame_times_rejected(time):
    with pytest.raises(InvalidVisualInput):
        validate_frames([EncodedFrame(bmp_bytes(), time)])


def test_bounds_and_monotonic_timestamps():
    frame = EncodedFrame(bmp_bytes())
    for frames, limits in [([], {}), ([frame] * 33, {}), ([frame, frame], {}),
                          ([frame], {"max_bytes": 10}), ([frame], {"max_pixels": 4})]:
        with pytest.raises(InvalidVisualInput):
            validate_frames(frames, **limits)


def test_sampling_is_bounded_deterministic_and_keeps_endpoints():
    frames = tuple(EncodedFrame(bmp_bytes(), i) for i in range(20))
    selected, indices = sample_frames(frames, 4)
    assert indices == (0, 6, 13, 19)
    assert [f.timestamp_seconds for f in selected] == list(indices)
    assert sample_frames(frames, 4) == (selected, indices)
    assert sample_frames(frames, 1)[1] == (0,)
    for count in (0, 9, True):
        with pytest.raises(ValueError):
            sample_frames(frames, count)


def normalize_output(features=None, output=None, threshold=0):
    features = features if features is not None else ObservableFeatures()
    output = output if output is not None else VisualModelOutput()
    return normalize(
        features, output, quality={}, sampling={"sampled_frame_count": 1},
        feature_metadata=NoExpressionExtractor.metadata, model_metadata=NoExpressionModel.metadata,
        minimum_confidence=threshold,
    )


def test_default_abstains_and_observable_expression_uncertainty_is_not_internal_state():
    baseline = normalize_output()
    assert baseline.abstained and baseline.confidence is None
    assert baseline.labels["features"]["action_unit_intensities"] is None
    assert baseline.labels["expression_probabilities"] is None
    result = normalize_output(
        ObservableFeatures(action_unit_intensities={"AU12": 2.5}),
        VisualModelOutput(expression_probabilities={"smiling": .5, "frowning": .5},
                          probability_kind="exclusive", confidence=.5,
                          confidence_method="uncalibrated_softmax"), threshold=.6,
    )
    assert result.abstained
    assert result.uncertainty["normalized_entropy"] == pytest.approx(1)
    assert result.uncertainty_method == "normalized_observed_expression_entropy"
    assert result.labels["internal_state_inference"] == "not_supported"
    assert not result.uncertainty["calibrated"]


@pytest.mark.parametrize("key", ["student_id", "face_embedding", "age", "gender", "ethnicity", "depression", "happy"])
def test_identity_protected_attributes_diagnoses_and_internal_state_labels_rejected(key):
    with pytest.raises(ValueError):
        normalize_output(output=VisualModelOutput(expression_probabilities={key: 1}, probability_kind="exclusive"))
    with pytest.raises(ValueError):
        normalize_features(ObservableFeatures(expression_measurements={key: .5}))


@pytest.mark.parametrize("output", [
    VisualModelOutput(confidence=float("nan")), VisualModelOutput(confidence=.9),
    VisualModelOutput(expression_probabilities={"smiling": 2}, probability_kind="independent"),
    VisualModelOutput(expression_probabilities={"smiling": .6}, probability_kind="exclusive"),
    VisualModelOutput(expression_probabilities={"smiling": .5}),
])
def test_invalid_probabilities_and_confidence_rejected(output):
    with pytest.raises(ValueError):
        normalize_output(output=output)
    with pytest.raises(ValueError):
        normalize_features(ObservableFeatures(action_unit_intensities={"AU12": 6}))


@pytest.mark.parametrize("failure", ["extractor", "model", "success"])
def test_sampled_temporary_media_cleanup_after_success_and_failures(tmp_path, failure):
    extractor = Mock(metadata=NoExpressionExtractor.metadata)
    model = Mock(metadata=NoExpressionModel.metadata)
    extractor.extract.return_value = ObservableFeatures()
    model.predict.return_value = VisualModelOutput(abstained=True)
    if failure == "extractor":
        extractor.extract.side_effect = RuntimeError("private pixels")
    elif failure == "model":
        model.predict.side_effect = RuntimeError("private pixels")
    service = VisualInferenceService(extractor, model, temporary_directory=tmp_path, sample_count=2)
    frames = tuple(EncodedFrame(bmp_bytes(), i) for i in range(5))
    if failure == "success":
        result = service.analyze_frames(frames)
        assert result.sampled_frame_count == 2 and result.labels["sampling"]["indices"] == [0, 4]
    else:
        with pytest.raises(RuntimeError):
            service.analyze_frames(frames)
    assert list(tmp_path.iterdir()) == []


def test_invalid_unsampled_frames_rejected_before_file_creation(tmp_path):
    model = Mock(metadata=NoExpressionModel.metadata)
    service = VisualInferenceService(NoExpressionExtractor(), model, temporary_directory=tmp_path, sample_count=1)
    with pytest.raises(InvalidVisualInput):
        service.analyze_frames([EncodedFrame(bmp_bytes()), EncodedFrame(b"invalid", 1)])
    model.predict.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_forbidden_features_block_model_before_prediction(tmp_path):
    extractor = Mock(metadata=NoExpressionExtractor.metadata)
    extractor.extract.return_value = ObservableFeatures(expression_measurements={"face_embedding": .5})
    model = Mock(metadata=NoExpressionModel.metadata)
    with pytest.raises(ValueError):
        VisualInferenceService(extractor, model, temporary_directory=tmp_path).analyze_frames([EncodedFrame(bmp_bytes())])
    model.predict.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_registry_requires_explicit_registered_provenance():
    registry = VisualRegistry()
    registry.register("quality-only", NoExpressionExtractor)
    assert registry.resolve("quality-only").metadata.version == "1"
    with pytest.raises(ValueError):
        registry.resolve("unknown")
    with pytest.raises(ValueError):
        registry.register("quality-only", NoExpressionExtractor)


@pytest.mark.parametrize("state", ["disabled", "declined", "withdrawn", "superseded", "outdated-disclosure"])
def test_visual_consent_blocks_service_and_temporary_files(api, monkeypatch, tmp_path, state):
    settings, _ = configure(api, monkeypatch, tmp_path, visual=state != "declined", enabled=state != "disabled")
    if state == "withdrawn":
        withdraw_consent(api[1], api[2]["alice"].id)
        api[1].commit()
    elif state == "superseded":
        record_consent(api[1], api[2]["alice"].id, POLICY_VERSION, text_processing=True, visual_processing=False)
        api[1].commit()
    elif state == "outdated-disclosure":
        settings.visual_sample_count = 2
    process = Mock()
    monkeypatch.setattr(VisualInferenceService, "analyze_frames", process)
    with pytest.raises(ConsentDenied):
        analyze(api)
    assert upload(api).status_code == 409
    process.assert_not_called()
    assert list(tmp_path.iterdir()) == []
    assert api[1].scalar(select(func.count()).select_from(ModelInference)) == 0
    assert api[1].scalar(select(func.count()).select_from(MediaAsset)) == 0


def test_denied_visual_upload_never_consumes_body_and_text_still_works(api, monkeypatch, tmp_path):
    settings, _ = configure(api, monkeypatch, tmp_path, visual=False, enabled=True)
    request = Mock(spec=Request)
    request.client = None
    with pytest.raises(HTTPException) as denied:
        asyncio.run(upload_visual(session_id(api), request, api[1], api[2]["alice"]))
    assert denied.value.status_code == 409
    request.stream.assert_not_called()
    # Unrelated visual configuration changes must not disable text in the onboarding/chat UI.
    settings.visual_sample_count = 2
    onboarding = api[0].get("/api/v1/me/onboarding", headers=headers(api, "alice"))
    assert onboarding.status_code == 200 and onboarding.json()["completed"] is True
    response = send(api, text="I would like text support without sharing images")
    assert response.status_code == 200, response.text
    assert response.json()["messages"][-1]["text"]
    assert api[1].scalar(select(func.count()).select_from(ModelInference)) == 0


def test_quality_only_persistence_traceability_access_and_no_raw_retention(api, monkeypatch, tmp_path):
    _, receipt = configure(api, monkeypatch, tmp_path, retain=True)
    response = upload(api)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "abstained"
    assert data["sampled_frame_count"] == 1
    assert data["model_version"] == "1" and data["feature_version"] == "1"
    assert data["consent_record_id"] == receipt.id
    assert data["consent_state"]["visual_processing_at_submission"] is True
    assert data["created_at"] and data["completed_at"] and data["started_at"]
    assert data["confidence"] is None and data["result"]["expression_probabilities"] is None
    assert not data["raw_retained"]
    assert api[1].scalar(select(func.count()).select_from(VisualAnalysis)) == 1
    assert api[1].scalar(select(func.count()).select_from(MediaAsset)) == 0
    assert list((tmp_path / "temporary").iterdir()) == []
    path = f"/api/v1/visual-analyses/{data['analysis_id']}"
    for name in ("bob", "admin", "other_counselor"):
        assert api[0].get(path, headers=headers(api, name)).status_code == 403
    assert api[0].get(path, headers=headers(api, "alice")).status_code == 200
    assert upload(api, name="bob", target="alice").status_code == 403


def test_sequence_sampling_and_upload_rejections(api, monkeypatch, tmp_path):
    configure(api, monkeypatch, tmp_path)
    response = upload(api, data=frame_envelope(10), content_type="application/json")
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["sampled_frame_count"] == 8
    assert data["result"]["sampling"]["input_frame_count"] == 10
    assert data["result"]["sampling"]["indices"][-1] == 9
    assert upload(api, data=b"a" * 3_000_001).status_code == 413
    assert upload(api, data=b"").status_code == 422
    assert upload(api, content_type="video/mp4").status_code == 415
    assert upload(api, data=b"{", content_type="application/json").status_code == 422
    invalid = upload(api, data=b"invalid BMP")
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "Invalid visual frame envelope"
    assert list((tmp_path / "temporary").iterdir()) == []


@pytest.mark.parametrize("value", [
    {"frames": [], "student_id": "identity"}, {"frames": [{"path": "../private.bmp"}]},
    {"frames": [{"bmp_base64": "not-base64", "timestamp_seconds": 0}]},
])
def test_frame_envelope_rejects_paths_and_extra_fields(value):
    with pytest.raises(InvalidVisualInput):
        parse_frames(json.dumps(value).encode(), "application/json")


@pytest.mark.parametrize("mode", ["failure", "withdraw", "new-receipt", "processor-change"])
def test_model_failure_revocation_and_configuration_changes_discard_results(api, monkeypatch, tmp_path, mode):
    class Experimental(NoExpressionModel):
        metadata = VisualMetadata("expression-test", "weights-2")

        def predict(self, features):
            if mode == "failure":
                raise RuntimeError("private face details")
            if mode == "withdraw":
                withdraw_consent(api[1], api[2]["alice"].id)
                api[1].commit()
            elif mode == "new-receipt":
                record_consent(api[1], api[2]["alice"].id, POLICY_VERSION, visual_processing=False)
                api[1].commit()
            else:
                settings.visual_analysis_model = "no-expression"
            return VisualModelOutput(expression_probabilities={"smiling": 1}, probability_kind="exclusive")

    monkeypatch.setitem(models._factories, "experimental", Experimental)
    settings, _ = configure(api, monkeypatch, tmp_path, model="experimental")
    response = upload(api)
    assert response.status_code == 201, response.text
    assert response.json()["status"] in {"failed", "cancelled"}
    assert "private face" not in response.text
    assert api[1].scalar(select(func.count()).select_from(VisualAnalysis)) == 0
    assert api[1].scalar(select(func.count()).select_from(MediaAsset)) == 0
    assert list((tmp_path / "temporary").iterdir()) == []


def test_reviewed_extractor_and_model_outputs_persist_with_versions(api, monkeypatch, tmp_path):
    class Extractor(NoExpressionExtractor):
        metadata = VisualMetadata("observable-test", "feature-3")

        def extract(self, frames):
            return ObservableFeatures(action_unit_intensities={"AU12": 2.5},
                                      expression_measurements={"lip_corner_raise": .6})

    class Model(NoExpressionModel):
        metadata = VisualMetadata("expression-test", "weights-42")

        def predict(self, features):
            return VisualModelOutput(expression_probabilities={"smiling": .7, "no_clear_expression": .3},
                                      probability_kind="exclusive", confidence=.7,
                                      confidence_method="uncalibrated-test-softmax")

    monkeypatch.setitem(extractors._factories, "experimental", Extractor)
    monkeypatch.setitem(models._factories, "experimental", Model)
    configure(api, monkeypatch, tmp_path, extractor="experimental", model="experimental")
    data = upload(api).json()
    assert data["status"] == "completed" and data["model_version"] == "weights-42"
    assert data["feature_version"] == "feature-3" and data["confidence"] == .7
    assert data["uncertainty_method"] == "normalized_observed_expression_entropy"
    assert data["result"]["features"]["action_unit_intensities"]["AU12"] == 2.5
    assert data["result"]["internal_state_inference"] == "not_supported"


def test_existing_model_configuration_cannot_be_silently_replaced(api, monkeypatch, tmp_path):
    configure(api, monkeypatch, tmp_path)
    analyze(api)
    original = NoExpressionExtractor.metadata
    monkeypatch.setattr(NoExpressionExtractor, "metadata", replace(original, version="2"))
    record_consent(api[1], api[2]["alice"].id, POLICY_VERSION,
                   disclosure_snapshot=policy_document(), visual_processing=True)
    api[1].commit()
    with pytest.raises(ValueError, match="new model version"):
        analyze(api)
