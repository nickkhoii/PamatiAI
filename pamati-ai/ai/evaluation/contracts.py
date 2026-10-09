"""Validated, versioned contracts for offline empirical evaluation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NOT_EVALUATED = "Not evaluated — labeled dataset required."
VARIANTS = {
    "text_only": ("text",),
    "audio_only": ("audio",),
    "visual_only": ("visual",),
    "text_audio": ("text", "audio"),
    "text_visual": ("text", "visual"),
    "audio_visual": ("audio", "visual"),
    "all_available": ("text", "audio", "visual"),
}
Variant = Literal[
    "text_only",
    "audio_only",
    "visual_only",
    "text_audio",
    "text_visual",
    "audio_visual",
    "all_available",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ModelVersion(Contract):
    identifier: str = Field(min_length=1, max_length=180, pattern=r"^[A-Za-z0-9_.:/-]+$")
    version: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:/-]+$")
    adapter_version: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:/-]+$")
    artifact_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    configuration_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    parameters: dict[
        Literal[
            "batch_size",
            "learning_rate",
            "epochs",
            "max_sequence_length",
            "temperature",
            "regularization",
            "dropout",
            "weight_decay",
            "threshold",
            "minimum_confidence",
            "seed",
            "num_beams",
            "top_p",
            "num_layers",
            "hidden_size",
        ],
        float | int | bool,
    ] = Field(default_factory=dict)

    @field_validator("version", "adapter_version")
    @classmethod
    def pinned_versions(cls, value):
        if value.casefold() in {
            "main",
            "master",
            "head",
            "latest",
            "unspecified",
            "unversioned",
            "deployment-unspecified",
        }:
            raise ValueError("Pin a concrete model and adapter version, not a moving alias")
        return value

    @field_validator("parameters")
    @classmethod
    def parameter_values(cls, value):
        import math

        if any(not math.isfinite(v) for v in value.values()):
            raise ValueError("Model parameters must be finite numerical values")
        return value


class DatasetSpec(Contract):
    identifier: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    version: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    target: Literal["sentiment", "emotion", "observed_expression"]
    task: Literal["single_label", "multilabel"] = "single_label"
    labels: list[str] = Field(min_length=2, max_length=100)
    annotation_version: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    label_mapping_version: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    source_reference: str = Field(min_length=1, max_length=250, pattern=r"^[A-Za-z0-9_.:/-]+$")
    license_reference: str = Field(min_length=1, max_length=250, pattern=r"^[A-Za-z0-9_.:/-]+$")
    population_scope: Literal["public_benchmark", "institutional_consented"]
    evidence_kind: Literal["empirical_labeled", "synthetic_fixture", "unlabeled"]
    split_unit: Literal["sample", "participant"] = "participant"
    positive_label: str | None = None

    @model_validator(mode="after")
    def taxonomy(self):
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("Label vocabulary must be unique")
        import re

        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", label) for label in self.labels):
            raise ValueError("Use coded label names, not free text")
        if self.positive_label is not None and (
            self.task != "single_label"
            or len(self.labels) != 2
            or self.positive_label not in self.labels
        ):
            raise ValueError("A positive label is only meaningful for binary single-label tasks")
        return self


class Sample(Contract):
    sample_id: str = Field(min_length=1, max_length=250)
    group_id: str | None = Field(default=None, min_length=1, max_length=250)
    split: Literal["train", "validation", "test"]
    labels: list[str] | None = None
    modalities: list[Literal["text", "audio", "visual"]] = Field(min_length=1, max_length=3)
    # Private evaluator inputs; never included in reports or research exports.
    text: str | None = None
    audio: str | None = None
    visual: str | None = None
    input_sha256: dict[Literal["text", "audio", "visual"], str] = Field(default_factory=dict)

    @field_validator("input_sha256")
    @classmethod
    def hashes(cls, value):
        import re

        if any(not re.fullmatch(r"[a-f0-9]{64}", digest) for digest in value.values()):
            raise ValueError("Input fingerprints require SHA-256 digests")
        return value

    @field_validator("modalities")
    @classmethod
    def distinct(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Duplicate modalities")
        return value


class Prediction(Contract):
    sample_id: str = Field(min_length=1, max_length=250)
    variant: Variant
    labels: list[str] | None = None
    probabilities: dict[str, float] | None = None
    probability_kind: Literal["exclusive", "independent"] | None = None
    abstained: bool = False
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    input_modalities: list[Literal["text", "audio", "visual"]] = Field(min_length=1, max_length=3)
    model_versions: list[ModelVersion] = Field(min_length=1)


class ExperimentSpec(Contract):
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    dataset: DatasetSpec
    variants: list[Variant] = Field(default_factory=lambda: list(VARIANTS), min_length=1)
    model_versions: dict[str, list[ModelVersion]] = Field(default_factory=dict)
    seed: int = Field(default=0, ge=0, le=2**32 - 1)
    split: Literal["validation", "test"] = "test"
    cohort_policy: Literal["paired_complete", "per_variant"] = "paired_complete"
    minimum_confidence: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)
    decision_threshold: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    calibration_bins: int = Field(default=10, ge=2, le=50)
    bootstrap_repetitions: int = Field(default=0, ge=0, le=2000)
    # No arbitrary configuration dictionaries that might carry identifiers or API keys.
    fusion_weights: dict[Literal["text", "audio", "visual"], float] = Field(default_factory=dict)
    dataset_path: str | None = None
    predictions_path: str | None = None
    system_path: str | None = None

    @model_validator(mode="after")
    def versions(self):
        import math

        if len(set(self.variants)) != len(self.variants):
            raise ValueError("Duplicate experimental variants")
        if set(self.model_versions) - set(self.variants):
            raise ValueError("Model version keys must be selected variants")
        if any(not versions for versions in self.model_versions.values()):
            raise ValueError("Model provenance cannot be empty")
        if any(not math.isfinite(w) or not 0 <= w <= 1000 for w in self.fusion_weights.values()):
            raise ValueError("Fusion weights must be finite and nonnegative")
        return self
