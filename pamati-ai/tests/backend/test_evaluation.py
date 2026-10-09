"""Exact numerical fixtures validate code only; never empirical model results."""

import json
import math
from copy import deepcopy

import pytest
from ai.evaluation.adapters import RegisteredTextPredictor, execute_predictors
from ai.evaluation.contracts import (
    NOT_EVALUATED,
    VARIANTS,
    DatasetSpec,
    ExperimentSpec,
    ModelVersion,
    Prediction,
    Sample,
)
from ai.evaluation.experiments import run_experiment, run_manifest
from ai.evaluation.metrics import classification_metrics, roc_auc
from ai.evaluation.reports import write_report
from ai.evaluation.system import SystemObservation, evaluate_system, sus_score


def dataset(task="single_label", labels=None, **updates):
    values = {
        "identifier": "fixture",
        "version": "1",
        "target": "sentiment",
        "task": task,
        "labels": labels or ["negative", "positive"],
        "annotation_version": "fixture-1",
        "label_mapping_version": "identity-1",
        "source_reference": "unit-test-fixture",
        "license_reference": "test-only",
        "population_scope": "public_benchmark",
        "evidence_kind": "synthetic_fixture",
        "positive_label": "positive" if task == "single_label" else None,
    }
    values.update(updates)
    return DatasetSpec(**values)


def version():
    return ModelVersion(identifier="fixture-model", version="1", adapter_version="1")


def spec(variants=None, **updates):
    variants = variants or ["text_only"]
    values = {
        "experiment_id": "test-experiment",
        "dataset": dataset(),
        "variants": variants,
        "model_versions": {v: [version()] for v in variants},
    }
    values.update(updates)
    return ExperimentSpec(**values)


def sample(identifier, label="positive", modalities=None, **updates):
    values = {
        "sample_id": identifier,
        "group_id": "participant-" + identifier,
        "split": "test",
        "labels": [label],
        "modalities": modalities or ["text"],
    }
    values.update(updates)
    return Sample(**values)


def prediction(identifier, variant="text_only", label="positive", **updates):
    values = {
        "sample_id": identifier,
        "variant": variant,
        "labels": [label],
        "model_versions": [version()],
        "input_modalities": list(VARIANTS[variant]),
    }
    values.update(updates)
    return Prediction(**values)


def test_binary_metrics_and_abstention_denominators():
    metrics = classification_metrics(
        [["negative"], ["negative"], ["positive"], ["positive"]],
        [["negative"], ["positive"], ["positive"], None],
        [None] * 4,
        dataset(),
    )
    assert metrics["accuracy"] == pytest.approx(2 / 3)
    assert metrics["end_to_end_accuracy"] == 0.5
    assert metrics["coverage"] == 0.75
    assert metrics["precision"] == 0.5 and metrics["recall"] == 1
    assert metrics["f1"] == pytest.approx(2 / 3)
    assert metrics["confusion_matrix"]["matrix"] == [[1, 1], [0, 1]]
    assert metrics["probability_metrics"]["roc_auc"]["value"] is None


def test_probability_metrics_binary_auc_brier_log_loss_ece():
    probabilities = [{"negative": 0.8, "positive": 0.2}, {"negative": 0.1, "positive": 0.9}]
    metrics = classification_metrics(
        [["negative"], ["positive"]], [["negative"], ["positive"]], probabilities, dataset(), bins=2
    )
    scores = metrics["probability_metrics"]
    assert scores["roc_auc"]["value"] == 1
    assert scores["brier_score"] == pytest.approx(0.025)
    assert scores["log_loss"] == pytest.approx(-(math.log(0.8) + math.log(0.9)) / 2)
    assert scores["calibration"]["ece"] == pytest.approx(0.15)
    assert roc_auc([False, True], [0.5, 0.5])["value"] == 0.5
    assert roc_auc([True, True], [0.3, 0.8])["value"] is None


def test_multiclass_macro_weighted_and_missing_class_auc():
    data = dataset(labels=["negative", "neutral", "positive"], positive_label=None)
    truth = [["negative"], ["negative"], ["positive"]]
    outputs = [["negative"], ["positive"], ["positive"]]
    probabilities = [
        {"negative": 0.6, "neutral": 0.1, "positive": 0.3},
        {"negative": 0.2, "neutral": 0.1, "positive": 0.7},
        {"negative": 0.1, "neutral": 0.1, "positive": 0.8},
    ]
    metrics = classification_metrics(truth, outputs, probabilities, data)
    assert metrics["macro_f1"] == pytest.approx(4 / 9)
    assert metrics["weighted_f1"] == pytest.approx(2 / 3)
    assert metrics["probability_metrics"]["roc_auc"]["value"] is None
    assert metrics["per_class"]["neutral"]["support"] == 0


def test_multilabel_is_not_silently_single_label():
    data = dataset("multilabel", ["joy", "sadness"], target="emotion")
    truth, outputs = [["joy"], ["sadness"], []], [["joy", "sadness"], ["sadness"], []]
    metrics = classification_metrics(truth, outputs, [None] * 3, data)
    assert metrics["accuracy"] == pytest.approx(2 / 3)
    assert metrics["hamming_loss"] == pytest.approx(1 / 6)
    assert metrics["f1"] == pytest.approx(0.8)
    assert metrics["macro_f1"] == pytest.approx(5 / 6)
    assert metrics["confusion_matrix"]["per_label"]["joy"] == [[2, 0], [0, 1]]


def test_empty_data_emits_required_phrase_and_null_metrics():
    report = run_experiment(spec(list(VARIANTS)), [])
    assert report["status"] == NOT_EVALUATED
    assert all(
        r["status"] == NOT_EVALUATED and r["metrics"] is None for r in report["variants"].values()
    )
    assert all(r["metrics"] is None for r in report["system_evaluation"].values())


def test_paired_seven_variant_cohort_and_failed_prediction_coverage():
    variants = list(VARIANTS)
    samples = [sample("aligned", modalities=["text", "audio", "visual"]), sample("incomplete")]
    outputs = [prediction("aligned", v) for v in variants if v != "audio_only"]
    report = run_experiment(spec(variants), samples, outputs)
    assert {r["cohort_sample_count"] for r in report["variants"].values()} == {1}
    assert len({r["cohort_sha256"] for r in report["variants"].values()}) == 1
    assert report["variants"]["audio_only"]["metrics"] is None
    assert "Synthetic fixture" in report["variants"]["text_only"]["status"]
    samples.append(sample("failed", modalities=["text", "audio", "visual"]))
    report = run_experiment(spec(variants), samples, outputs)
    assert report["variants"]["text_only"]["metrics"]["coverage"] == 0.5
    assert report["variants"]["text_only"]["missing_prediction_count"] == 1


def test_all_available_really_uses_present_modalities():
    output = prediction("a", "all_available", input_modalities=["text", "audio"])
    report = run_experiment(
        spec(["all_available"]), [sample("a", modalities=["text", "audio"])], [output]
    )
    assert report["variants"]["all_available"]["actual_modality_patterns"] == {"audio+text": 1}


@pytest.mark.parametrize(
    "change",
    [
        "group_leakage",
        "sample_duplicate",
        "content_leakage",
        "unknown_label",
        "version",
        "input_modalities",
        "probability_kind",
        "nan_probability",
        "duplicate_prediction",
    ],
)
def test_reject_invalid_research_inputs(change):
    samples, outputs = [sample("a")], [prediction("a")]
    experiment = spec()
    if change == "group_leakage":
        samples.append(sample("b", split="train", group_id=samples[0].group_id))
    elif change == "sample_duplicate":
        samples.append(sample("a", split="train"))
    elif change == "content_leakage":
        samples[0].text = "duplicate content"
        samples.append(sample("b", split="train", text="duplicate content"))
    elif change == "unknown_label":
        samples[0].labels = ["unmapped"]
    elif change == "version":
        outputs[0].model_versions = [version().model_copy(update={"version": "2"})]
    elif change == "input_modalities":
        outputs[0].input_modalities = ["audio"]
    elif change in {"probability_kind", "nan_probability"}:
        outputs[0].probabilities = {"negative": 0.2, "positive": 0.8}
        outputs[0].probability_kind = "independent" if change == "probability_kind" else "exclusive"
        if change == "nan_probability":
            outputs[0].probabilities["positive"] = float("nan")
    else:
        outputs.append(deepcopy(outputs[0]))
    with pytest.raises(ValueError):
        run_experiment(experiment, samples, outputs)


def test_bootstrap_reproducible_and_reports_protect_raw_inputs(tmp_path):
    samples = [
        sample("EMAIL-alice@example.com", text="PRIVATE transcript"),
        sample("b", "negative"),
    ]
    outputs = [prediction(s.sample_id, label=s.labels[0]) for s in samples]
    experiment = spec(bootstrap_repetitions=40, seed=7)
    a = run_experiment(experiment, samples, outputs, timestamp="2026-10-09T00:00:00+00:00")
    b = run_experiment(experiment, samples, outputs, timestamp=a["timestamp"])
    assert a == b
    folder = write_report(a, tmp_path)
    for path in folder.iterdir():
        text = path.read_text()
        assert "alice@example.com" not in text and "PRIVATE transcript" not in text
    with pytest.raises(FileExistsError):
        write_report(a, tmp_path)


def test_manifest_relative_paths_and_private_error_redaction(tmp_path):
    experiment = spec(dataset_path="samples.jsonl", predictions_path="outputs.jsonl")
    (tmp_path / "manifest.json").write_text(experiment.model_dump_json())
    (tmp_path / "samples.jsonl").write_text(sample("a").model_dump_json() + "\n")
    (tmp_path / "outputs.jsonl").write_text(prediction("a").model_dump_json() + "\n")
    assert (
        run_manifest(tmp_path / "manifest.json")["variants"]["text_only"]["metrics"]["accuracy"]
        == 1
    )
    (tmp_path / "samples.jsonl").write_text(json.dumps({"email": "PRIVATE@example.com"}))
    with pytest.raises(ValueError) as caught:
        run_manifest(tmp_path / "manifest.json")
    assert "PRIVATE" not in str(caught.value)


def observation(dimension, **fields):
    return SystemObservation(
        dimension=dimension,
        unit_id="unit-1",
        evidence_kind="synthetic_fixture",
        rubric_version="rubric-1",
        **fields,
    )


def test_system_metrics_and_undefined_kappa():
    assert sus_score([5, 1, 5, 1, 5, 1, 5, 1, 5, 1]) == 100
    records = [
        observation(
            "usability", group_id="respondent-1", sus_responses=[5, 1, 5, 1, 5, 1, 5, 1, 5, 1]
        ),
        observation("response_latency", phase="complete_response", duration_ms=125.0, success=True),
        observation(
            "conversation_quality", ratings={"autonomy": 4}, annotation_source="human_reviewed"
        ),
        observation(
            "safety_behavior",
            expected_behaviors=["support", "human_help"],
            observed_behaviors=["support"],
            annotation_source="human_reviewed",
        ),
        observation(
            "human_review_agreement",
            rater_a="counselor-a",
            rater_b="counselor-b",
            label_a="follow_up",
            label_b="follow_up",
            agreement_source="human_human",
        ),
    ]
    result = evaluate_system(records)
    assert result["usability"]["strata"][0]["metrics"]["sus"]["mean"] == 100
    assert result["safety_behavior"]["strata"][0]["metrics"]["required_behavior_coverage"] == 0.5
    assert result["human_review_agreement"]["strata"][0]["metrics"]["cohen_kappa"] is None
    with pytest.raises(ValueError):
        sus_score([5] * 9)
    with pytest.raises(ValueError):
        evaluate_system([records[1], records[1]])


def test_real_registered_text_adapter_never_fabricates_probabilities():
    predictor = RegisteredTextPredictor("lexicon-baseline")
    experiment = spec(model_versions={"text_only": predictor.model_versions})
    samples = [sample("a", text="happy"), sample("b", text="unrecognized vocabulary")]
    outputs, latency = execute_predictors(experiment, samples, {"text_only": predictor})
    report = run_experiment(experiment, samples, outputs, latency)
    assert outputs[0].labels == ["positive"]
    assert outputs[1].abstained
    metrics = report["variants"]["text_only"]["metrics"]
    assert metrics["coverage"] == 0.5
    assert metrics["probability_metrics"]["roc_auc"]["value"] is None
    assert all(r.duration_ms >= 0 for r in latency)


def test_multiclass_and_multilabel_probability_metrics_are_defined_only_with_class_variation():
    multiclass = dataset(labels=["negative", "neutral", "positive"], positive_label=None)
    truth = [["negative"], ["neutral"], ["positive"]]
    probabilities = [
        {label: float(label == row[0]) for label in multiclass.labels} for row in truth
    ]
    metrics = classification_metrics(truth, truth, probabilities, multiclass)
    assert metrics["probability_metrics"]["roc_auc"]["value"] == 1
    assert metrics["probability_metrics"]["brier_score"] == 0
    assert metrics["probability_metrics"]["calibration"]["ece"] == 0
    multilabel = dataset("multilabel", ["joy", "sadness"], target="emotion")
    gold = [["joy"], ["sadness"]]
    probabilities = [{"joy": 0.9, "sadness": 0.2}, {"joy": 0.1, "sadness": 0.8}]
    scores = classification_metrics(gold, gold, probabilities, multilabel)["probability_metrics"]
    assert scores["roc_auc"]["value"] == 1
    assert scores["brier_score"] == pytest.approx(0.025)
    assert scores["calibration"]["ece"] == pytest.approx(0.15)


def test_paired_differences_resample_shared_groups_and_are_reproducible():
    experiment = spec(["text_only", "audio_only"], bootstrap_repetitions=40, seed=21)
    samples = [
        sample("a", modalities=["text", "audio"]),
        sample("b", "negative", modalities=["text", "audio"]),
    ]
    outputs = [
        prediction("a"),
        prediction("b", label="negative"),
        prediction("a", "audio_only"),
        prediction("b", "audio_only"),
    ]
    report = run_experiment(experiment, samples, outputs)
    compared = report["paired_comparisons"][0]
    assert compared["deltas"]["end_to_end_accuracy"] == -0.5
    assert compared["paired_sample_count"] == 2
    assert (
        compared["interval"]
        == run_experiment(experiment, samples, outputs)["paired_comparisons"][0]["interval"]
    )


def test_required_status_is_literal_and_confidence_does_not_become_roc_scores():
    assert NOT_EVALUATED == "Not evaluated \u2014 labeled dataset required."
    experiment = spec(minimum_confidence=0.9)
    report = run_experiment(experiment, [sample("a")], [prediction("a", confidence=0.4)])
    metrics = report["variants"]["text_only"]["metrics"]
    assert metrics["coverage"] == 0 and metrics["accuracy"] is None
    assert metrics["end_to_end_accuracy"] == 0


def test_unevaluated_variants_do_not_become_zero_accuracy_results():
    experiment = spec(["text_only", "audio_only"], cohort_policy="per_variant")
    report = run_experiment(experiment, [sample("a")], [prediction("a")])
    assert report["variants"]["audio_only"]["metrics"] is None
    assert report["paired_comparisons"][0]["status"].startswith("Not applicable")
    with pytest.raises(ValueError):
        run_experiment(spec(dataset=dataset(evidence_kind="unlabeled")), [sample("a")])
