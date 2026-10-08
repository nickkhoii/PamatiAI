from dataclasses import dataclass, field
from typing import Protocol

from ai.audio.validation import AudioInput


@dataclass(frozen=True)
class AudioModelMetadata:
    identifier: str
    version: str
    adapter_version: str
    configuration: dict = field(default_factory=dict)
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class AudioModelOutput:
    emotion_probabilities: dict[str, float] | None = None
    emotion_probability_kind: str | None = None
    confidence: float | None = None
    confidence_method: str | None = None
    word_count: int | None = None
    speech_timing_method: str | None = None
    abstained: bool = False
    limitations: tuple[str, ...] = ()


class AudioModel(Protocol):
    metadata: AudioModelMetadata

    def predict(self, sample: AudioInput, features: dict) -> AudioModelOutput: ...
