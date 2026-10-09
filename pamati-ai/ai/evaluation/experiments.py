"""Immutable experiment reports from real labeled inputs or explicitly marked fixtures."""

import platform
import subprocess
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from ai.evaluation.contracts import NOT_EVALUATED, VARIANTS, ExperimentSpec, Prediction
from ai.evaluation.datasets import canonical_digest, file_digest, load_samples, read_jsonl
from ai.evaluation.metrics import classification_metrics, validate_probabilities
from ai.evaluation.statistics import bootstrap, paired_comparisons
from ai.evaluation.system import SystemObservation, evaluate_system

VERSION = "pamati-evaluation-v1"


def code_provenance():
    folder = Path(__file__).parent
    hashes = {p.name: file_digest(p) for p in sorted(folder.glob("*.py"))}
    try:
        revision = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=folder, stderr=subprocess.DEVNULL, timeout=5
            )
            .decode()
            .strip()
        )
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=folder, stderr=subprocess.DEVNULL, timeout=5
            )
        )
    except (OSError, subprocess.SubprocessError):
        revision, dirty = None, None
    return {
        "git_revision": revision,
        "working_tree_dirty": dirty,
        "evaluation_source_sha256": hashes,
        "python": platform.python_version(),
        "pydantic": version("pydantic"),
        "metric_implementation": VERSION,
    }


def public_spec(spec):
    return spec.model_dump(exclude={"dataset_path", "predictions_path", "system_path"})


def expected_modalities(sample, variant):
    return set(sample.modalities) if variant == "all_available" else set(VARIANTS[variant])


def prediction_labels(prediction, spec):
    if prediction.probabilities is not None:
        expected_kind = "exclusive" if spec.dataset.task == "single_label" else "independent"
        if prediction.probability_kind != expected_kind:
            raise ValueError(
                "Probability semantics do not match the evaluation task; confidence is not a probability distribution."
            )
        validate_probabilities(prediction.probabilities, spec.dataset)
    elif prediction.probability_kind is not None:
        raise ValueError("Probability semantics without probabilities")
    if prediction.labels is not None:
        if len(set(prediction.labels)) != len(prediction.labels) or set(prediction.labels) - set(
            spec.dataset.labels
        ):
            raise ValueError("Prediction vocabulary does not match the dataset label mapping")
        if spec.dataset.task == "single_label" and len(prediction.labels) != 1:
            raise ValueError("Single-label predictions require exactly one class")
    if prediction.abstained or (
        spec.minimum_confidence > 0
        and (prediction.confidence is None or prediction.confidence < spec.minimum_confidence)
    ):
        return None
    if prediction.labels is not None:
        return prediction.labels
    if prediction.probabilities is None:
        raise ValueError("Non-abstaining predictions require labels or declared probabilities")
    if spec.dataset.task == "multilabel":
        return [
            label
            for label in spec.dataset.labels
            if prediction.probabilities[label] >= spec.decision_threshold
        ]
    if len(spec.dataset.labels) == 2 and spec.dataset.positive_label:
        positive = spec.dataset.positive_label
        return [
            positive
            if prediction.probabilities[positive] >= spec.decision_threshold
            else next(l for l in spec.dataset.labels if l != positive)
        ]
    return [max(spec.dataset.labels, key=lambda label: prediction.probabilities[label])]


def run_experiment(
    spec,
    samples=None,
    predictions=None,
    system_observations=None,
    *,
    timestamp=None,
    dataset_sha256=None,
    predictions_sha256=None,
    system_sha256=None,
):
    """Pure evaluation; no training, downloads, fabricated observations or raw report rows."""
    from ai.evaluation.datasets import validate_dataset

    samples, predictions = list(samples or []), list(predictions or [])
    validate_dataset(samples, spec.dataset)
    if spec.dataset.evidence_kind == "unlabeled" and any(s.labels is not None for s in samples):
        raise ValueError(
            "Dataset declared unlabeled but contains annotations; correct provenance before evaluation"
        )
    stamp = timestamp or datetime.now(UTC).isoformat()
    if datetime.fromisoformat(stamp).tzinfo is None:
        raise ValueError("Experiment timestamp requires a timezone")
    selected = [s for s in samples if s.split == spec.split]
    labeled = [s for s in selected if s.labels is not None]
    all_by_id = {s.sample_id: s for s in samples}
    by_prediction = {}
    resolved = {}
    for prediction in predictions:
        key = (prediction.variant, prediction.sample_id)
        if key in by_prediction:
            raise ValueError("Duplicate prediction for a sample and modality variant")
        sample = all_by_id.get(prediction.sample_id)
        if not sample or sample.split != spec.split or prediction.variant not in spec.variants:
            raise ValueError(
                "Prediction is not aligned with the declared evaluation split and variants"
            )
        models = spec.model_versions.get(prediction.variant)
        if not models or [m.model_dump() for m in models] != [
            m.model_dump() for m in prediction.model_versions
        ]:
            raise ValueError(
                "Prediction model/adapter provenance differs from the experiment manifest"
            )
        expected = expected_modalities(sample, prediction.variant)
        if (
            expected - set(sample.modalities)
            or len(set(prediction.input_modalities)) != len(prediction.input_modalities)
            or set(prediction.input_modalities) != expected
        ):
            raise ValueError(
                "Prediction inputs differ from the declared ablation; missing modalities cannot masquerade as unimodal or fused outputs"
            )
        resolved[key] = prediction_labels(prediction, spec)
        by_prediction[key] = prediction
    paired = [
        s
        for s in labeled
        if all(not (expected_modalities(s, v) - set(s.modalities)) for v in spec.variants)
    ]
    results = {}
    for variant in spec.variants:
        cohort = (
            paired
            if spec.cohort_policy == "paired_complete"
            else [s for s in labeled if not (expected_modalities(s, variant) - set(s.modalities))]
        )
        base = {
            "required_modalities": "all modalities actually present on each sample"
            if variant == "all_available"
            else list(VARIANTS[variant]),
            "cohort_sample_count": len(cohort),
            "missing_modality_exclusions": len(labeled) - len(cohort),
            "actual_modality_patterns": dict(
                Counter("+".join(sorted(expected_modalities(s, variant))) for s in cohort)
            ),
            "cohort_sha256": canonical_digest(sorted(s.sample_id for s in cohort)),
            "model_versions": [v.model_dump() for v in spec.model_versions.get(variant, [])],
        }
        if not labeled:
            results[variant] = {**base, "status": NOT_EVALUATED, "metrics": None}
            continue
        if not cohort:
            results[variant] = {
                **base,
                "status": "Not evaluated — aligned labeled modalities required.",
                "metrics": None,
            }
            continue
        if not spec.model_versions.get(variant) or not any(
            (variant, s.sample_id) in by_prediction for s in cohort
        ):
            results[variant] = {
                **base,
                "status": "Not evaluated — versioned model predictions required.",
                "metrics": None,
            }
            continue
        truth = [s.labels for s in cohort]
        outputs = [resolved.get((variant, s.sample_id)) for s in cohort]
        probabilities = [
            by_prediction[(variant, s.sample_id)].probabilities
            if (variant, s.sample_id) in by_prediction
            else None
            for s in cohort
        ]
        results[variant] = {
            **base,
            "status": "evaluated"
            if spec.dataset.evidence_kind == "empirical_labeled"
            else "Synthetic fixture — not empirical research.",
            "missing_prediction_count": sum(
                (variant, s.sample_id) not in by_prediction for s in cohort
            ),
            "abstention_or_confidence_rejection_count": sum(
                (variant, s.sample_id) in by_prediction and output is None
                for s, output in zip(cohort, outputs, strict=True)
            ),
            "metrics": classification_metrics(
                truth, outputs, probabilities, spec.dataset, spec.calibration_bins
            ),
            "uncertainty": bootstrap(
                cohort, truth, outputs, spec.dataset, spec.bootstrap_repetitions, spec.seed
            ),
        }
    config = public_spec(spec)
    return {
        "schema_version": VERSION,
        "experiment_id": spec.experiment_id,
        "timestamp": stamp,
        "status": NOT_EVALUATED if not labeled else "completed; see per-variant evaluation status",
        "experiment": config,
        "parameters": {
            k: v
            for k, v in config.items()
            if k not in {"experiment_id", "dataset", "model_versions"}
        },
        "configuration_sha256": canonical_digest(config),
        "dataset_sha256": dataset_sha256 or canonical_digest([s.model_dump() for s in samples]),
        "predictions_sha256": predictions_sha256
        or canonical_digest([p.model_dump() for p in predictions]),
        "system_observations_sha256": system_sha256
        or canonical_digest([r.model_dump() for r in system_observations or []]),
        "provenance": code_provenance(),
        "selected_split_samples": len(selected),
        "unlabeled_exclusions": len(selected) - len(labeled),
        "labeled_sample_count": len(labeled),
        "prediction_source": "supplied versioned model outputs; hashes bind the inputs, not an independent verification of model execution",
        "comparability": "same eligible labeled cohort across selected variants; prediction failures remain in denominator"
        if spec.cohort_policy == "paired_complete"
        else "different per-variant cohorts; do not interpret raw differences as paired modality improvements",
        "variants": results,
        "paired_comparisons": paired_comparisons(
            spec,
            paired,
            {v: [resolved.get((v, s.sample_id)) for s in paired] for v in spec.variants},
            results,
        ),
        "system_evaluation": evaluate_system(system_observations or []),
        "limitations": [
            "Observed expression is not internal emotion or diagnosis.",
            "Benchmark performance does not establish effectiveness for Filipino students or clinical outcomes.",
            "No direct identifiers, text, media paths, notes or individual prediction rows are exported.",
            "Input fingerprints bind private artifacts and are not anonymization; keep reports access-controlled.",
        ],
    }


def run_manifest(path, *, predictors=None):
    """Paths resolve against the manifest, not the operator's working directory."""
    path = Path(path).resolve()
    try:
        spec = ExperimentSpec.model_validate_json(path.read_text(encoding="utf-8-sig"))
    except ValueError:
        raise ValueError(
            "Invalid experiment manifest; inspect the private configuration locally."
        ) from None
    paths = {
        key: (path.parent / getattr(spec, key)).resolve() if getattr(spec, key) else None
        for key in ("dataset_path", "predictions_path", "system_path")
    }
    # Absent explicitly configured files are configuration errors, not fabricated empty runs.
    for candidate in paths.values():
        if candidate is not None and not candidate.is_file():
            raise ValueError("A configured experiment input file is missing.")
    samples = load_samples(paths["dataset_path"], spec.dataset) if paths["dataset_path"] else []
    predictions = (
        read_jsonl(paths["predictions_path"], Prediction) if paths["predictions_path"] else []
    )
    system = read_jsonl(paths["system_path"], SystemObservation) if paths["system_path"] else []
    if predictors is not None:
        if paths["predictions_path"]:
            raise ValueError("Choose inference or imported predictions, not both")
        from ai.evaluation.adapters import execute_predictors

        predictions, latency = execute_predictors(spec, samples, predictors)
        system.extend(latency)
    return run_experiment(
        spec,
        samples,
        predictions,
        system,
        dataset_sha256=file_digest(paths["dataset_path"]) if paths["dataset_path"] else None,
        predictions_sha256=file_digest(paths["predictions_path"])
        if paths["predictions_path"]
        else None,
        system_sha256=file_digest(paths["system_path"])
        if paths["system_path"] and predictors is None
        else None,
    )
