"""Dependency-free metrics with explicit estimands, denominators and unavailable values."""

import math
from collections import Counter
from statistics import mean


def ratio(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def binary_counts(truth, predicted):
    return {
        "true_positive": sum(a and b for a, b in zip(truth, predicted, strict=True)),
        "false_positive": sum(not a and b for a, b in zip(truth, predicted, strict=True)),
        "false_negative": sum(a and not b for a, b in zip(truth, predicted, strict=True)),
        "true_negative": sum(not a and not b for a, b in zip(truth, predicted, strict=True)),
    }


def class_metrics(counts):
    tp, fp, fn = (counts[k] for k in ("true_positive", "false_positive", "false_negative"))
    return {
        "precision": ratio(tp, tp + fp),
        "recall": ratio(tp, tp + fn),
        "f1": ratio(2 * tp, 2 * tp + fp + fn),
        "support": tp + fn,
    }


def roc_auc(truth, scores):
    """Binary Mann-Whitney rank AUC with average ranks for ties, O(n log n)."""
    if (
        len(truth) != len(scores)
        or any(type(y) is not bool for y in truth)
        or any(
            isinstance(s, bool) or not isinstance(s, (int, float)) or not math.isfinite(s)
            for s in scores
        )
    ):
        raise ValueError("ROC-AUC requires aligned binary outcomes and finite ranking scores")
    positive = sum(truth)
    negative = len(truth) - positive
    if not positive or not negative:
        return {
            "value": None,
            "reason": "Both positive and negative labeled examples are required.",
        }
    ordered = sorted(zip(scores, truth, strict=True))
    rank_sum, index = 0.0, 0
    while index < len(ordered):
        stop = index + 1
        while stop < len(ordered) and ordered[stop][0] == ordered[index][0]:
            stop += 1
        rank = (index + 1 + stop) / 2
        rank_sum += rank * sum(flag for _, flag in ordered[index:stop])
        index = stop
    return {
        "value": (rank_sum - positive * (positive + 1) / 2) / (positive * negative),
        "reason": None,
    }


def reliability(confidences, outcomes, bins):
    groups = [[] for _ in range(bins)]
    for confidence, outcome in zip(confidences, outcomes, strict=True):
        groups[min(bins - 1, int(confidence * bins))].append((confidence, outcome))
    result, error = [], 0.0
    for index, group in enumerate(groups):
        confidence = mean(x for x, _ in group) if group else None
        observed = mean(y for _, y in group) if group else None
        if group:
            error += len(group) / len(confidences) * abs(confidence - observed)
        result.append(
            {
                "lower": index / bins,
                "upper": (index + 1) / bins,
                "count": len(group),
                "mean_probability": confidence,
                "observed_frequency": observed,
            }
        )
    return {"ece": error, "bins": result, "binning": "equal_width; final bin includes 1"}


def validate_probabilities(probabilities, spec):
    if set(probabilities) != set(spec.labels):
        raise ValueError("Probability vocabulary must exactly match the declared label order")
    if any(
        isinstance(p, bool)
        or not isinstance(p, (float, int))
        or not math.isfinite(p)
        or not 0 <= p <= 1
        for p in probabilities.values()
    ):
        raise ValueError("Probabilities must be finite values between zero and one")
    if spec.task == "single_label" and not math.isclose(
        sum(probabilities.values()), 1, abs_tol=1e-6
    ):
        raise ValueError("Exclusive class probabilities must sum to one")


def probability_metrics(truth, predicted, probabilities, spec, bins):
    if not probabilities or any(p is None for p in probabilities):
        return {
            "status": "Not applicable — complete declared probabilities required.",
            "roc_auc": {
                "value": None,
                "reason": "Hard labels and heuristic confidence are not ROC-AUC inputs.",
            },
            "brier_score": None,
            "log_loss": None,
            "calibration": None,
            "sample_count": 0,
        }
    for p in probabilities:
        validate_probabilities(p, spec)
    auc = {
        label: roc_auc([label in y for y in truth], [p[label] for p in probabilities])
        for label in spec.labels
    }
    if spec.task == "single_label" and len(spec.labels) == 2:
        result_auc = (
            auc[spec.positive_label]
            if spec.positive_label
            else {"value": None, "reason": "Predeclare the binary positive label."}
        )
        result_auc = {
            **result_auc,
            "method": "binary positive-label probability",
            "positive_label": spec.positive_label,
        }
    else:
        values = [a["value"] for a in auc.values()]
        result_auc = {
            "value": mean(values) if all(v is not None for v in values) else None,
            "reason": None
            if all(v is not None for v in values)
            else "Every declared label needs positive and negative examples for macro ROC-AUC.",
            "method": "macro one-vs-rest",
            "per_label": auc,
        }
    epsilon = 1e-15
    if spec.task == "single_label":
        loss = -mean(
            math.log(max(epsilon, p[y[0]])) for y, p in zip(truth, probabilities, strict=True)
        )
        if len(spec.labels) == 2 and spec.positive_label:
            brier = mean(
                (p[spec.positive_label] - (spec.positive_label in y)) ** 2
                for y, p in zip(truth, probabilities, strict=True)
            )
            brier_definition = "mean squared positive-label probability error; range [0,1]"
        else:
            brier = mean(
                sum((p[label] - (label in y)) ** 2 for label in spec.labels)
                for y, p in zip(truth, probabilities, strict=True)
            )
            brier_definition = "mean sum of squared class probability errors; unscaled range [0,2]"
        calibration = reliability(
            [p[y[0]] for p, y in zip(probabilities, predicted, strict=True)],
            [a == b for a, b in zip(truth, predicted, strict=True)],
            bins,
        )
        calibration["method"] = "predicted-label confidence versus correctness"
    else:
        losses, errors = [], []
        calibrations = {}
        for label in spec.labels:
            outcomes = [label in y for y in truth]
            values = [p[label] for p in probabilities]
            errors.extend((p - y) ** 2 for p, y in zip(values, outcomes, strict=True))
            losses.extend(
                -math.log(max(epsilon, p if y else 1 - p))
                for p, y in zip(values, outcomes, strict=True)
            )
            calibrations[label] = reliability(values, outcomes, bins)
        loss, brier = mean(losses), mean(errors)
        brier_definition = "mean squared Bernoulli error across samples and labels; range [0,1]"
        calibration = {
            "method": "mean label-wise Bernoulli ECE",
            "ece": mean(v["ece"] for v in calibrations.values()),
            "per_label": calibrations,
        }
    return {
        "status": "evaluated",
        "sample_count": len(truth),
        "roc_auc": result_auc,
        "brier_score": brier,
        "brier_definition": brier_definition,
        "log_loss": loss,
        "log_loss_clipping_epsilon": epsilon,
        "calibration": calibration,
        "interpretation": "ECE depends on binning and sample size; Brier/log loss also reflect discrimination, not calibration alone.",
    }


def classification_metrics(truth, predicted, probabilities, spec, bins=10):
    """Abstentions are excluded from selective metrics and counted as failures end-to-end."""
    if not (len(truth) == len(predicted) == len(probabilities)):
        raise ValueError("Unaligned metric inputs")
    if not truth:
        return None
    for values in truth:
        if (
            not isinstance(values, list)
            or len(set(values)) != len(values)
            or set(values) - set(spec.labels)
        ):
            raise ValueError("Invalid gold labels")
        if spec.task == "single_label" and len(values) != 1:
            raise ValueError("Single-label gold examples require exactly one label")
    for values in predicted:
        if values is not None and (
            len(set(values)) != len(values)
            or set(values) - set(spec.labels)
            or (spec.task == "single_label" and len(values) != 1)
        ):
            raise ValueError("Invalid prediction labels")
    selected = [i for i, p in enumerate(predicted) if p is not None]
    count = len(truth)
    covered_truth, covered_prediction = (
        [truth[i] for i in selected],
        [predicted[i] for i in selected],
    )
    correct = sum(set(a) == set(b) for a, b in zip(covered_truth, covered_prediction, strict=True))
    base = {
        "labeled_sample_count": count,
        "predicted_sample_count": len(selected),
        "uncovered_sample_count": count - len(selected),
        "coverage": len(selected) / count,
        "end_to_end_accuracy": correct / count,
        "dataset_label_support": dict(Counter(label for y in truth for label in y)),
        "zero_division_policy": "0 for class precision/recall/F1 with zero denominator; all declared labels included in macro averages",
        "metric_population": "answered examples only; compare coverage and end_to_end_accuracy alongside selective metrics",
    }
    if not selected:
        return {
            **base,
            "accuracy": None,
            "precision": None,
            "recall": None,
            "f1": None,
            "macro_f1": None,
            "weighted_f1": None,
            "confusion_matrix": None,
            "probability_metrics": {"status": "Not applicable — no answered predictions."},
        }
    truth, predicted = covered_truth, covered_prediction
    per_class = {
        label: class_metrics(
            binary_counts([label in y for y in truth], [label in y for y in predicted])
        )
        for label in spec.labels
    }
    macro = {
        metric: mean(v[metric] for v in per_class.values())
        for metric in ("precision", "recall", "f1")
    }
    support = sum(v["support"] for v in per_class.values())
    weighted = {
        metric: ratio(sum(v[metric] * v["support"] for v in per_class.values()), support)
        for metric in ("precision", "recall", "f1")
    }
    if spec.task == "single_label":
        matrix = [
            [
                sum(a == [left] and b == [right] for a, b in zip(truth, predicted, strict=True))
                for right in spec.labels
            ]
            for left in spec.labels
        ]
        confusion = {
            "labels": spec.labels,
            "rows": "gold",
            "columns": "predicted",
            "matrix": matrix,
        }
        average = (
            per_class[spec.positive_label]
            if len(spec.labels) == 2 and spec.positive_label
            else macro
        )
        averaging = (
            "binary positive label" if len(spec.labels) == 2 and spec.positive_label else "macro"
        )
        extra = {}
    else:
        counts = {
            label: binary_counts([label in y for y in truth], [label in y for y in predicted])
            for label in spec.labels
        }
        total = {k: sum(v[k] for v in counts.values()) for k in next(iter(counts.values()))}
        average = class_metrics(total)
        averaging = "micro over label decisions"
        confusion = {
            "labels": spec.labels,
            "per_label": {
                label: [
                    [v["true_negative"], v["false_positive"]],
                    [v["false_negative"], v["true_positive"]],
                ]
                for label, v in counts.items()
            },
            "rows": "gold [absent,present]",
            "columns": "predicted [absent,present]",
        }
        extra = {
            "hamming_loss": sum(len(set(a) ^ set(b)) for a, b in zip(truth, predicted, strict=True))
            / (len(truth) * len(spec.labels))
        }
    return {
        **base,
        **extra,
        "accuracy": correct / len(selected),
        "accuracy_definition": "exact label-set match"
        if spec.task == "multilabel"
        else "exact class match",
        "precision": average["precision"],
        "recall": average["recall"],
        "f1": average["f1"],
        "averaging": averaging,
        "macro_f1": macro["f1"],
        "weighted_f1": weighted["f1"],
        "macro_precision": macro["precision"],
        "macro_recall": macro["recall"],
        "weighted_precision": weighted["precision"],
        "weighted_recall": weighted["recall"],
        "per_class": per_class,
        "confusion_matrix": confusion,
        "probability_metrics": probability_metrics(
            truth, predicted, [probabilities[i] for i in selected], spec, bins
        ),
    }
