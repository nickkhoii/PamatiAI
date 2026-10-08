from dataclasses import dataclass, field
from typing import Protocol

from ai.text.preprocessing import TextInput


@dataclass(frozen=True)
class ModelMetadata:
    identifier: str
    version: str
    adapter_version: str
    configuration: dict = field(default_factory=dict)
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelOutput:
    polarity: float | None = None
    category: str | None = None
    sentiment_probabilities: dict[str, float] | None = None
    emotion_probabilities: dict[str, float] | None = None
    confidence: float | None = None
    confidence_method: str | None = None
    emotion_probability_kind: str | None = None
    abstained: bool = False
    limitations: tuple[str, ...] = ()


class TextModel(Protocol):
    metadata: ModelMetadata

    def predict(self, sample: TextInput) -> ModelOutput: ...
