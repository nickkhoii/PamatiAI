from dataclasses import dataclass, field
from typing import Protocol

MODALITIES = ("text", "audio", "visual")


@dataclass(frozen=True)
class ModalityObservation:
    modality: str
    source_id: str
    status: str
    output: dict | None
    model_identifier: str
    model_version: str
    timestamp: str
    model_configuration: dict = field(default_factory=dict)
    preprocessing_version: str = "unspecified"
    adapter_version: str = "unspecified"
    confidence: float | None = None
    uncertainty: dict | None = None
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class FusionMetadata:
    identifier: str
    version: str
    learned: bool = False
    artifact_sha256: str | None = None
    configuration: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FusionConfig:
    weights: dict[str, float] = field(default_factory=lambda: {m: 1.0 for m in MODALITIES})
    minimum_confidence: float = 0.0
    maximum_source_span_seconds: float = 300.0


@dataclass(frozen=True)
class ProbabilityChannel:
    target: str
    probability_kind: str
    probabilities: dict[str, float]
    source_ids: tuple[str, ...]
    effective_weights: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class FusionOutput:
    channels: tuple[ProbabilityChannel, ...] = ()
    confidence: float | None = None
    confidence_method: str | None = None
    abstained: bool = False
    limitations: tuple[str, ...] = ()


class FusionStrategy(Protocol):
    """Learned adapters receive derived observations and a variable-size modality set.

    They must tolerate missing inputs, declare artifact provenance, and never reinterpret
    visual expression as internal state, protected attributes, identity, or diagnosis.
    """

    metadata: FusionMetadata

    def fuse(self, observations: tuple[ModalityObservation, ...], config: FusionConfig) -> FusionOutput: ...
