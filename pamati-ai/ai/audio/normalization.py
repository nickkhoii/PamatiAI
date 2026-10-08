from dataclasses import dataclass

from ai.audio.interface import AudioModelOutput
from ai.text.confidence import bounded, probabilities, uncertainty

LIMITATIONS = (
    "Research acoustic features and model estimates; never psychiatric diagnoses.",
    "Microphone quality, background noise, accent, language and speaking differences affect measurements.",
    "Disability, assistive speech devices and accessibility needs must not be interpreted as pathology.",
    "Energy gating does not distinguish speech from noise; pitch can contain octave and aliasing errors.",
    "Confidence is uncalibrated and is not clinical certainty.",
)
EMOTIONS = {"joy", "sadness", "anger", "fear", "disgust", "surprise", "neutral",
            "calm", "excitement", "boredom"}


@dataclass(frozen=True)
class NormalizedAudioResult:
    labels: dict
    duration_seconds: float
    confidence: float | None
    uncertainty: dict
    uncertainty_method: str
    abstained: bool
    limitations: tuple[str, ...]


def normalize(features, output: AudioModelOutput, *, minimum_confidence=0.0, limitations=()):
    bounded(minimum_confidence)
    if output.emotion_probabilities is not None:
        if output.emotion_probability_kind not in {"exclusive", "independent"}:
            raise ValueError("Declare emotion probability semantics")
        if output.emotion_probabilities.keys() - EMOTIONS:
            raise ValueError("Map model labels to the supported affect vocabulary")
    emotions = probabilities(output.emotion_probabilities,
                             distribution=output.emotion_probability_kind == "exclusive")
    confidence = bounded(output.confidence) if output.confidence is not None else None
    if confidence is not None and not output.confidence_method:
        raise ValueError("Confidence requires a method")
    if output.word_count is not None:
        if (type(output.word_count) is not int or output.word_count < 0
                or not output.speech_timing_method):
            raise ValueError("Word count requires valid speech timing provenance")
        features = {**features, "speech_rate": {
            "words_per_minute": output.word_count * 60 / features["duration_seconds"],
            "word_count": output.word_count, "method": output.speech_timing_method,
            "denominator": "entire_recording_including_pauses",
        }}
    info = uncertainty(emotions if output.emotion_probability_kind == "exclusive" else None)
    if info["method"] != "unavailable":
        info["method"] = "normalized_emotion_entropy"
    info.update(confidence_method=output.confidence_method, minimum_confidence=minimum_confidence)
    abstained = output.abstained or (minimum_confidence > 0 and (
        confidence is None or confidence < minimum_confidence
    ))
    return NormalizedAudioResult(
        labels={"schema_version": "1", "interpretation": "research_estimate",
                "features": features, "emotion_probabilities": emotions,
                "emotion_probability_kind": output.emotion_probability_kind, "abstained": abstained},
        duration_seconds=features["duration_seconds"], confidence=confidence,
        uncertainty=info, uncertainty_method=info["method"], abstained=abstained,
        limitations=tuple(dict.fromkeys((*LIMITATIONS, *limitations, *output.limitations))),
    )
