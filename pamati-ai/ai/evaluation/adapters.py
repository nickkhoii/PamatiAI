"""Adapters for real inference. No synthetic predictions and no automatic downloads."""

from copy import deepcopy
from time import perf_counter_ns
from typing import Protocol

from ai.evaluation.contracts import ModelVersion, Prediction
from ai.evaluation.experiments import expected_modalities
from ai.evaluation.system import SystemObservation


class EvaluationPredictor(Protocol):
    """An external unimodal/fusion model must actually use exactly input_modalities.

    Never substitute production fusion's separate semantic channels for a universal
    emotion label. Adapters must explicitly map a benchmark's versioned target.
    """

    model_versions: list[ModelVersion]

    def predict(self, sample, *, input_modalities: tuple[str, ...], dataset) -> Prediction: ...


class RegisteredTextPredictor:
    def __init__(self, model_name):
        import inspect

        from ai.evaluation.datasets import canonical_digest, file_digest
        from ai.text import confidence, normalization, preprocessing, service
        from ai.text.registry import registry
        from ai.text.service import InferenceService

        self.model = registry.resolve(model_name)
        self.service = InferenceService(self.model)
        meta = self.model.metadata
        implementation = {}
        for implementation_object in (
            self.model.__class__,
            confidence,
            normalization,
            preprocessing,
            service,
        ):
            try:
                implementation[implementation_object.__name__] = file_digest(
                    inspect.getfile(implementation_object)
                )
            except (OSError, TypeError):
                # Compiled/external adapters must supply their own artifact provenance.
                continue
        self.model_versions = [
            ModelVersion(
                identifier=meta.identifier,
                version=meta.version,
                adapter_version=meta.adapter_version,
                configuration_sha256=canonical_digest(
                    {
                        "configuration": meta.configuration,
                        "preprocessing_version": preprocessing.VERSION,
                        "implementation_sha256": implementation,
                    }
                ),
            )
        ]

    def predict(self, sample, *, input_modalities, dataset):
        if input_modalities != ("text",) or sample.text is None:
            raise ValueError("The registered text adapter requires actual text-only input")
        if dataset.target not in {"sentiment", "emotion"}:
            raise ValueError("Text sentiment is not an observed visual-expression classifier")
        output = self.service.analyze_text(sample.text)
        probabilities = output.labels.get(
            "sentiment_probabilities" if dataset.target == "sentiment" else "emotion_probabilities"
        )
        category = (
            output.labels.get("sentiment_category") if dataset.target == "sentiment" else None
        )
        kind = (
            "exclusive"
            if dataset.target == "sentiment"
            else output.labels.get("emotion_probability_kind")
        )
        return Prediction(
            sample_id=sample.sample_id,
            variant="text_only",
            input_modalities=["text"],
            model_versions=self.model_versions,
            labels=[category] if category else None,
            probabilities=probabilities,
            probability_kind=kind if probabilities else None,
            confidence=output.confidence,
            abstained=output.abstained or (probabilities is None and category is None),
        )


def execute_predictors(spec, samples, predictors):
    """Return genuine model outputs plus measured latency observations.

    Missing predictors stay missing. Adapter failures are explicit abstentions and
    failed latency observations, with no private exception strings in reports.
    """
    import random

    random.seed(spec.seed)
    from ai.evaluation.datasets import validate_dataset
    from ai.evaluation.experiments import prediction_labels

    validate_dataset(samples, spec.dataset)
    predictions, latency = [], []
    for variant in spec.variants:
        predictor = predictors.get(variant)
        if predictor is None:
            continue
        if predictor.model_versions != spec.model_versions.get(variant):
            raise ValueError("Predictor provenance does not match the experiment manifest")
        for sample in samples:
            if sample.split != spec.split or sample.labels is None:
                continue
            inputs = expected_modalities(sample, variant)
            if inputs - set(sample.modalities):
                continue
            begin = perf_counter_ns()
            succeeded = True
            try:
                output = predictor.predict(
                    deepcopy(sample),
                    input_modalities=tuple(m for m in ("text", "audio", "visual") if m in inputs),
                    dataset=deepcopy(spec.dataset),
                )
            except Exception:  # noqa: BLE001 -- private adapter failures never become report text
                succeeded = False
                output = Prediction(
                    sample_id=sample.sample_id,
                    variant=variant,
                    input_modalities=sorted(inputs),
                    model_versions=predictor.model_versions,
                    abstained=True,
                )
            elapsed = (perf_counter_ns() - begin) / 1_000_000
            if (
                not isinstance(output, Prediction)
                or output.sample_id != sample.sample_id
                or output.variant != variant
                or set(output.input_modalities) != inputs
                or output.model_versions != predictor.model_versions
            ):
                raise ValueError(
                    "Evaluation adapter returned an unaligned or mislabeled prediction"
                )
            prediction_labels(output, spec)
            predictions.append(output)
            latency.append(
                SystemObservation(
                    dimension="response_latency",
                    unit_id=f"{variant}:{sample.sample_id}",
                    evidence_kind="synthetic_fixture"
                    if spec.dataset.evidence_kind == "synthetic_fixture"
                    else "empirical_observation",
                    rubric_version=f"model-inference-{variant}-v1",
                    phase="complete_response",
                    duration_ms=elapsed,
                    success=succeeded,
                )
            )
    return predictions, latency
