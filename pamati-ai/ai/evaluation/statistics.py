"""Seeded participant-cluster bootstrap for descriptive uncertainty, not causal claims."""

import random
from collections import defaultdict

from ai.evaluation.metrics import classification_metrics


def percentile(values, fraction):
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low = int(index)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (index - low)


def bootstrap(samples, truth, predicted, spec, repetitions, seed):
    if repetitions == 0:
        return {"status": "Not requested", "intervals": None}
    groups = defaultdict(list)
    for index, sample in enumerate(samples):
        groups[sample.group_id or sample.sample_id].append(index)
    if len(groups) < 2:
        return {
            "status": "Not applicable — at least two independent groups required.",
            "intervals": None,
        }
    generator = random.Random(seed)
    keys = sorted(groups)
    estimates = defaultdict(list)
    for _ in range(repetitions):
        indices = [i for key in generator.choices(keys, k=len(keys)) for i in groups[key]]
        metrics = classification_metrics(
            [truth[i] for i in indices],
            [predicted[i] for i in indices],
            [None] * len(indices),
            spec,
        )
        for name in ("end_to_end_accuracy", "accuracy", "macro_f1", "weighted_f1"):
            if metrics[name] is not None:
                estimates[name].append(metrics[name])
    return {
        "status": "evaluated",
        "method": "group-cluster percentile bootstrap",
        "confidence_level": 0.95,
        "seed": seed,
        "repetitions": repetitions,
        "group_count": len(groups),
        "intervals": {
            name: {
                "lower": percentile(values, 0.025),
                "upper": percentile(values, 0.975),
                "valid_replicates": len(values),
            }
            for name, values in estimates.items()
        },
        "limitations": "Descriptive uncertainty only; small clusters and model-selection/test reuse can invalidate inference. Not a significance test.",
    }


def paired_comparisons(spec, samples, predictions, results):
    """Predeclared first variant is the reference; only identical cohort outputs pair."""
    if len(spec.variants) < 2:
        return []
    if spec.cohort_policy != "paired_complete":
        return [{"status": "Not applicable — cohorts differ under per_variant policy."}]
    reference = spec.variants[0]
    generator = random.Random(spec.seed)
    groups = defaultdict(list)
    for index, sample in enumerate(samples):
        groups[sample.group_id or sample.sample_id].append(index)
    keys = sorted(groups)
    truth = [s.labels for s in samples]
    comparisons = []
    for variant in spec.variants[1:]:
        left, right = results[reference].get("metrics"), results[variant].get("metrics")
        if left is None or right is None:
            comparisons.append(
                {
                    "reference": reference,
                    "variant": variant,
                    "status": "Not evaluated — both variants require aligned predictions.",
                    "deltas": None,
                }
            )
            continue
        # Missing outputs are counted as failures; no coverage-conditioned winner claims.
        a, b = predictions[reference], predictions[variant]
        differences = [
            int(pb is not None and set(y) == set(pb)) - int(pa is not None and set(y) == set(pa))
            for y, pa, pb in zip(truth, a, b, strict=True)
        ]
        delta = sum(differences) / len(differences)
        interval = None
        if spec.bootstrap_repetitions and len(keys) >= 2:
            replicates = []
            for _ in range(spec.bootstrap_repetitions):
                indices = [i for key in generator.choices(keys, k=len(keys)) for i in groups[key]]
                replicates.append(sum(differences[i] for i in indices) / len(indices))
            interval = {
                "lower": percentile(replicates, 0.025),
                "upper": percentile(replicates, 0.975),
                "method": "paired group-cluster percentile bootstrap",
                "repetitions": spec.bootstrap_repetitions,
                "seed": spec.seed,
                "confidence_level": 0.95,
            }
        comparisons.append(
            {
                "reference": reference,
                "variant": variant,
                "status": "computed",
                "deltas": {
                    "end_to_end_accuracy": delta,
                    "coverage": right["coverage"] - left["coverage"],
                },
                "paired_sample_count": len(samples),
                "interval": interval,
                "interpretation": "variant minus reference; exploratory paired description, not a preapproved significance or clinical-effectiveness claim",
            }
        )
    return comparisons
