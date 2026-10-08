from dataclasses import dataclass, field
from typing import Protocol

from ai.visual.validation import Frame


@dataclass(frozen=True)
class VisualMetadata:
    identifier: str
    version: str
    configuration: dict = field(default_factory=dict)
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObservableFeatures:
    """Sequence summaries only. No embeddings, identities, demographics or diagnoses."""

    action_unit_intensities: dict[str, float] | None = None
    expression_measurements: dict[str, float] | None = None


@dataclass(frozen=True)
class VisualModelOutput:
    expression_probabilities: dict[str, float] | None = None
    probability_kind: str | None = None
    confidence: float | None = None
    confidence_method: str | None = None
    abstained: bool = False
    limitations: tuple[str, ...] = ()


class VisualFeatureExtractor(Protocol):
    metadata: VisualMetadata

    def extract(self, frames: tuple[Frame, ...]) -> ObservableFeatures: ...


class VisualModel(Protocol):
    metadata: VisualMetadata

    def predict(self, features: ObservableFeatures) -> VisualModelOutput: ...
