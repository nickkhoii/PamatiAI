import io
import math
import struct
import wave
from dataclasses import replace
from unittest.mock import Mock

import pytest
from ai.audio.features import extract_features
from ai.audio.files import RecordingStore, temporary_audio
from ai.audio.interface import AudioModelMetadata, AudioModelOutput
from ai.audio.normalization import normalize
from ai.audio.registry import AudioModelRegistry, FeaturesOnly, registry
from ai.audio.service import AudioInferenceService
from ai.audio.validation import InvalidAudio, validate_audio
from sqlalchemy import func, select
from test_auth import api as shared_api
from test_auth import headers

from app.audio_analysis import analyze_audio, purge_expired_recordings
from app.config import Settings
from app.consent_policy import POLICY_VERSION, policy_document
from app.models import AudioAnalysis, InteractionSession, MediaAsset, ModelInference, SystemSetting
from app.persistence import ConsentDenied, record_consent, withdraw_consent

api = shared_api


def wav_bytes(*, seconds=0.8, rate=8000, frequency=200, amplitude=.4, channels=1):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        values = [round(amplitude * 32767 * math.sin(2 * math.pi * frequency * n / rate))
                  for n in range(round(rate * seconds))]
        audio.writeframes(b"".join(struct.pack("<h", value) * channels for value in values))
    return output.getvalue()


def configure(api, monkeypatch, tmp_path, *, audio=True, retain=False, raw_storage=False,
              model="acoustic-features"):
    settings = Settings(
        audio_analysis_enabled=True, audio_analysis_model=model,
        allow_raw_media_storage=raw_storage,
        audio_temporary_directory=str(tmp_path / "temporary"),
        audio_storage_directory=str(tmp_path / "recordings"),
    )
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    db, users = api[1], api[2]
    receipt = record_consent(
        db, users["alice"].id, POLICY_VERSION, disclosure_snapshot=policy_document(),
        text_processing=True, audio_processing=audio, retain_audio=retain,
    )
    db.commit()
    return settings, receipt


def session_id(api, name="alice"):
    return api[1].scalar(select(InteractionSession.id).where(
        InteractionSession.student_id == api[2][name].id,
    ))


def analyze(api, data=None):
    return analyze_audio(api[1], session_id=session_id(api), student_id=api[2]["alice"].id,
                         data=wav_bytes() if data is None else data)


def upload(api, data=None, name="alice", target="alice", content_type="audio/wav"):
    return api[0].post(
        f"/api/v1/sessions/{session_id(api, target)}/audio-analyses",
        headers={**headers(api, name), "Content-Type": content_type},
        content=wav_bytes() if data is None else data,
    )


@pytest.mark.parametrize("data", [b"", b"not audio", wav_bytes(channels=2),
                                  wav_bytes(rate=4000), wav_bytes()[:-2]],
                         ids=["empty", "not-wav", "stereo", "unsupported-rate", "truncated"])
def test_audio_validation_rejects_invalid_or_unsupported_payload(data):
    with pytest.raises(InvalidAudio):
        validate_audio(data)


def test_duration_and_size_limits():
    data = wav_bytes()
    with pytest.raises(InvalidAudio):
        validate_audio(data, max_bytes=len(data) - 1)
    with pytest.raises(InvalidAudio):
        validate_audio(data, max_seconds=.4)
    assert validate_audio(data).duration_seconds == .8


def test_known_tone_energy_and_pitch_are_acoustic_only():
    features = extract_features(validate_audio(wav_bytes()))
    assert features["pitch_hz"]["mean"] == pytest.approx(200, abs=5)
    assert features["energy_dbfs"]["mean"] == pytest.approx(20 * math.log10(.4 / math.sqrt(2)), abs=.1)
    assert features["speech_rate"]["words_per_minute"] is None
    assert features["quality"]["speech_detection"] == "not_supported"


def test_silence_pause_summary_and_unavailable_pitch():
    features = extract_features(validate_audio(wav_bytes(amplitude=0)))
    assert features["pauses"]["count"] == 1
    assert features["pauses"]["duration_seconds"]["mean"] == pytest.approx(.8)
    assert features["pauses"]["quiet_fraction"] == pytest.approx(1)
    assert features["pitch_hz"]["mean"] is None
    assert features["prosody"]["acoustic_active_seconds"] == 0


def test_normalization_speech_timing_emotions_uncertainty():
    features = extract_features(validate_audio(wav_bytes()))
    result = normalize(features, AudioModelOutput(
        emotion_probabilities={"joy": .5, "sadness": .5}, emotion_probability_kind="exclusive",
        confidence=.4, confidence_method="uncalibrated_softmax", word_count=2,
        speech_timing_method="test-word-counter-v1",
    ), minimum_confidence=.6)
    assert result.abstained and result.confidence == .4
    assert result.labels["features"]["speech_rate"]["words_per_minute"] == 150
    assert result.uncertainty["normalized_entropy"] == pytest.approx(1)
    assert result.uncertainty_method == "normalized_emotion_entropy"
    assert not result.uncertainty["calibrated"]
    assert features["speech_rate"]["words_per_minute"] is None


@pytest.mark.parametrize("output", [
    AudioModelOutput(confidence=float("nan")), AudioModelOutput(confidence=.8),
    AudioModelOutput(emotion_probabilities={"joy": .6}),
    AudioModelOutput(emotion_probabilities={"joy": 2}, emotion_probability_kind="independent"),
    AudioModelOutput(emotion_probabilities={"joy": .8, "sadness": .8}, emotion_probability_kind="exclusive"),
    AudioModelOutput(emotion_probabilities={"depression": 1}, emotion_probability_kind="exclusive"),
    AudioModelOutput(word_count=-1, speech_timing_method="test"),
])
def test_invalid_or_diagnostic_outputs_rejected(output):
    with pytest.raises(ValueError):
        normalize(extract_features(validate_audio(wav_bytes())), output)


@pytest.mark.parametrize("failure", [False, True])
def test_temporary_file_cleanup_after_success_or_failure(tmp_path, failure):
    with pytest.raises(RuntimeError) if failure else temporary_audio(b"probe", tmp_path) as probe:
        if failure:
            with temporary_audio(b"probe", tmp_path) as path:
                assert path.exists()
                raise RuntimeError("model failed")
        else:
            assert probe.read_bytes() == b"probe"
    assert list(tmp_path.iterdir()) == []


def test_invalid_audio_and_model_failure_clean_temporary_files(tmp_path):
    model = Mock(metadata=FeaturesOnly.metadata)
    model.predict.side_effect = RuntimeError("private failure")
    service = AudioInferenceService(model, temporary_directory=tmp_path)
    with pytest.raises(InvalidAudio):
        service.analyze_bytes(b"invalid")
    assert list(tmp_path.iterdir()) == []
    model.predict.assert_not_called()
    with pytest.raises(RuntimeError):
        service.analyze_bytes(wav_bytes())
    assert list(tmp_path.iterdir()) == []


def test_recording_store_rejects_traversal_and_preserves_existing_files(tmp_path):
    store = RecordingStore(tmp_path)
    key = store.new_key()
    store.write(key, b"original")
    with pytest.raises(FileExistsError):
        store.write(key, b"replacement")
    assert (tmp_path / key).read_bytes() == b"original"
    for unsafe in ("../outside.wav", "C:/outside.wav", "/outside.wav", "user.wav"):
        with pytest.raises(ValueError):
            store.delete(unsafe)
    store.delete(key)
    assert list(tmp_path.iterdir()) == []


def test_model_registry_requires_explicit_registered_versions():
    models = AudioModelRegistry()
    models.register("local", FeaturesOnly)
    assert models.resolve("local").metadata.version == "1"
    with pytest.raises(ValueError):
        models.resolve("unknown")
    with pytest.raises(ValueError):
        models.register("local", FeaturesOnly)


@pytest.mark.parametrize("state", ["disabled", "declined", "withdrawn", "superseded"])
def test_consent_blocks_processing_before_validation_or_files(api, monkeypatch, tmp_path, state):
    settings, _ = configure(api, monkeypatch, tmp_path, audio=state != "declined")
    if state == "disabled":
        settings.audio_analysis_enabled = False
    elif state == "withdrawn":
        withdraw_consent(api[1], api[2]["alice"].id)
        api[1].commit()
    elif state == "superseded":
        record_consent(api[1], api[2]["alice"].id, POLICY_VERSION, audio_processing=False)
        api[1].commit()
    process = Mock()
    monkeypatch.setattr(AudioInferenceService, "analyze_bytes", process)
    with pytest.raises(ConsentDenied):
        analyze(api)
    assert upload(api).status_code == 409
    process.assert_not_called()
    assert list(tmp_path.iterdir()) == []
    assert api[1].scalar(select(func.count()).select_from(ModelInference)) == 0
    assert api[1].scalar(select(func.count()).select_from(MediaAsset)) == 0


def test_absent_audio_consent_blocks_decoder_and_upload_stream(api, monkeypatch, tmp_path):
    import asyncio

    from fastapi import HTTPException, Request

    from app.audio_routes import upload_audio

    settings = Settings(audio_analysis_enabled=True, audio_temporary_directory=str(tmp_path))
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    process = Mock()
    monkeypatch.setattr(AudioInferenceService, "analyze_bytes", process)
    assert upload(api).status_code == 409
    request = Mock(spec=Request)
    request.client = None
    with pytest.raises(HTTPException) as denied:
        asyncio.run(upload_audio(session_id(api), request, api[1], api[2]["alice"]))
    assert denied.value.status_code == 409
    process.assert_not_called()
    request.stream.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_no_consent_receipt_blocks_processing(api, monkeypatch, tmp_path):
    from app.models import Conversation, StudentProfile, User

    settings = Settings(audio_analysis_enabled=True, audio_temporary_directory=str(tmp_path))
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    db = api[1]
    student = User(email="no-consent@test.example", display_name="No receipt",
                   password_hash="unused", is_active=True)
    db.add(student)
    db.flush()
    db.add(StudentProfile(user_id=student.id))
    db.flush()
    conversation = Conversation(student_id=student.id)
    db.add(conversation)
    db.flush()
    interaction = InteractionSession(conversation_id=conversation.id, student_id=student.id)
    db.add(interaction)
    db.commit()
    process = Mock()
    monkeypatch.setattr(AudioInferenceService, "analyze_bytes", process)
    with pytest.raises(ConsentDenied, match="Active consent is required"):
        analyze_audio(db, session_id=interaction.id, student_id=student.id, data=wav_bytes())
    process.assert_not_called()
    assert list(tmp_path.iterdir()) == []
    assert db.scalar(select(func.count()).select_from(ModelInference)) == 0


def test_features_persist_independently_and_api_enforces_ownership(api, monkeypatch, tmp_path):
    _, receipt = configure(api, monkeypatch, tmp_path)
    response = upload(api)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "completed"
    assert data["feature_version"] == "acoustic-summary-v1"
    assert data["model_version"] == "1" and data["completed_at"] and data["started_at"]
    assert data["consent_record_id"] == receipt.id
    assert data["consent_state"]["audio_processing_at_submission"] is True
    assert data["duration_seconds"] == .8
    assert data["result"]["emotion_probabilities"] is None and data["confidence"] is None
    assert api[1].scalar(select(func.count()).select_from(AudioAnalysis)) == 1
    assert api[1].scalar(select(func.count()).select_from(MediaAsset)) == 0
    assert list((tmp_path / "temporary").iterdir()) == []
    assert not (tmp_path / "recordings").exists()
    path = f"/api/v1/audio-analyses/{data['analysis_id']}"
    for name in ("bob", "admin", "other_counselor"):
        assert api[0].get(path, headers=headers(api, name)).status_code == 403
    assert api[0].get(path, headers=headers(api, "alice")).status_code == 200
    assert upload(api, name="bob", target="alice").status_code == 403


@pytest.mark.parametrize("mode", ["failure", "withdraw", "new-receipt", "processor-change"])
def test_model_failure_or_revocation_discards_results_and_cleans_audio(api, monkeypatch, tmp_path, mode):
    class Experimental:
        metadata = AudioModelMetadata("audio-test", "weights-2", "adapter-1")

        def predict(self, sample, features):
            if mode == "failure":
                raise RuntimeError("private recording content")
            if mode == "withdraw":
                withdraw_consent(api[1], api[2]["alice"].id)
                api[1].commit()
            elif mode == "new-receipt":
                record_consent(api[1], api[2]["alice"].id, POLICY_VERSION, audio_processing=True)
                api[1].commit()
            elif mode == "processor-change":
                settings.audio_analysis_model = "acoustic-features"
            return AudioModelOutput(emotion_probabilities={"joy": 1},
                                    emotion_probability_kind="exclusive")

    monkeypatch.setitem(registry._factories, "experimental", Experimental)
    settings, _ = configure(api, monkeypatch, tmp_path, model="experimental", retain=True, raw_storage=True)
    response = upload(api)
    assert response.status_code == 201, response.text
    assert response.json()["status"] in {"failed", "cancelled"}
    assert "private recording" not in response.text
    assert api[1].scalar(select(func.count()).select_from(AudioAnalysis)) == 0
    assert api[1].scalar(select(func.count()).select_from(MediaAsset)) == 0
    assert list((tmp_path / "temporary").iterdir()) == []


@pytest.mark.parametrize("environment,user_permission,db_gate,retained", [
    (False, True, True, False), (True, False, True, False),
    (True, True, False, False), (True, True, True, True),
])
def test_raw_retention_requires_all_three_gates_and_supports_erasure(
    api, monkeypatch, tmp_path, environment, user_permission, db_gate, retained,
):
    configure(api, monkeypatch, tmp_path, retain=user_permission, raw_storage=environment)
    db = api[1]
    db.get(SystemSetting, "raw_media_retention").value = {"enabled": db_gate}
    db.commit()
    data = wav_bytes()
    inference_id = analyze(api, data)
    assert db.get(AudioAnalysis, inference_id)
    assets = list(db.scalars(select(MediaAsset)))
    assert len(assets) == int(retained)
    if retained:
        asset = assets[0]
        path = tmp_path / "recordings" / asset.storage_reference
        assert path.read_bytes() == data
        assert not asset.purged_at
        withdraw_consent(db, api[2]["alice"].id)
        db.commit()
        assert purge_expired_recordings(db) == 1
        assert not path.exists() and asset.purged_at
        assert db.get(AudioAnalysis, inference_id)  # Features do not depend on waveform retention.
        assert purge_expired_recordings(db) == 0


def test_upload_limits_format_and_changed_disclosure(api, monkeypatch, tmp_path):
    settings, _ = configure(api, monkeypatch, tmp_path)
    assert upload(api, content_type="audio/mpeg").status_code == 415
    assert upload(api, data=b"").status_code == 422
    settings.audio_max_bytes = 1024
    record_consent(api[1], api[2]["alice"].id, POLICY_VERSION,
                   disclosure_snapshot=policy_document(), audio_processing=True)
    api[1].commit()
    assert upload(api, data=b"a" * 1025).status_code == 413
    settings.audio_analysis_minimum_confidence = .5
    assert upload(api).status_code == 409


def test_raw_storage_failure_removes_new_file_and_preserves_derived_analysis(api, monkeypatch, tmp_path):
    from app.audio_analysis import retain_recording

    configure(api, monkeypatch, tmp_path, retain=True, raw_storage=True)
    db = api[1]
    inference_id = analyze(api)
    db.get(SystemSetting, "raw_media_retention").value = {"enabled": True}
    db.commit()
    monkeypatch.setattr("app.audio_analysis.audit", Mock(side_effect=RuntimeError("write transaction failed")))
    with pytest.raises(RuntimeError, match="write transaction failed"):
        retain_recording(db, inference_id, wav_bytes())
    assert list((tmp_path / "recordings").iterdir()) == []
    assert db.scalar(select(func.count()).select_from(MediaAsset)) == 0
    assert db.get(AudioAnalysis, inference_id)


def test_silence_and_invalid_upload_do_not_invent_emotions(api, monkeypatch, tmp_path):
    configure(api, monkeypatch, tmp_path)
    valid = upload(api, data=wav_bytes(amplitude=0)).json()
    assert valid["result"]["emotion_probabilities"] is None
    assert valid["result"]["features"]["pitch_hz"]["mean"] is None
    invalid = upload(api, data=b"not WAV")
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "Invalid PCM WAV upload"
    assert list((tmp_path / "temporary").iterdir()) == []


def test_optional_model_confidence_and_emotions_persist(api, monkeypatch, tmp_path):
    class Experimental(FeaturesOnly):
        metadata = replace(FeaturesOnly.metadata, identifier="audio-emotions", version="weights-42")

        def predict(self, sample, features):
            return AudioModelOutput(
                emotion_probabilities={"calm": .9, "fear": .1}, emotion_probability_kind="exclusive",
                confidence=.9, confidence_method="uncalibrated-softmax",
            )

    monkeypatch.setitem(registry._factories, "experimental", Experimental)
    configure(api, monkeypatch, tmp_path, model="experimental")
    data = upload(api).json()
    assert data["status"] == "completed" and data["model_version"] == "weights-42"
    assert data["confidence"] == .9 and data["uncertainty_method"] == "normalized_emotion_entropy"
    assert data["result"]["emotion_probabilities"]["calm"] == .9
