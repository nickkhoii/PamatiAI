"""Reproducible aggregate artifacts; raw samples and prediction rows are never reports."""

import csv
import io
import json
from pathlib import Path

from ai.evaluation.datasets import canonical_digest


def render_markdown(report):
    lines = [
        "# PamatiAI empirical experiment",
        "",
        f"Experiment: `{report['experiment_id']}`",
        f"Timestamp (UTC offset recorded): {report['timestamp']}",
        "",
        report["status"],
        "",
        f"Dataset: `{report['experiment']['dataset']['identifier']}` / `{report['experiment']['dataset']['version']}`",
        f"Evidence: `{report['experiment']['dataset']['evidence_kind']}`",
        f"Configuration SHA-256: `{report['configuration_sha256']}`",
        f"Dataset SHA-256: `{report['dataset_sha256']}`",
        "",
        report["comparability"],
        "",
        "| Variant | Status | N | Coverage | Accuracy (answered) | Macro F1 | Weighted F1 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]

    def value(v):
        return "Unavailable" if v is None else f"{v:.6f}"

    for variant, result in report["variants"].items():
        metrics = result.get("metrics") or {}
        lines.append(
            f"| {variant} | {result['status']} | {result['cohort_sample_count']} | {value(metrics.get('coverage'))} | {value(metrics.get('accuracy'))} | {value(metrics.get('macro_f1'))} | {value(metrics.get('weighted_f1'))} |"
        )
    for variant, result in report["variants"].items():
        confusion = (result.get("metrics") or {}).get("confusion_matrix")
        if confusion:
            lines.extend(
                [
                    "",
                    f"## {variant}: confusion matrix",
                    "",
                    "```json",
                    json.dumps(confusion, indent=2),
                    "```",
                    "",
                ]
            )
    lines.extend(
        [
            "",
            "## Paired comparisons",
            "",
            "```json",
            json.dumps(report["paired_comparisons"], sort_keys=True, indent=2),
            "```",
            "",
            "## System evaluation",
            "",
        ]
    )
    for name, result in report["system_evaluation"].items():
        lines.extend(
            [f"### {name}", "", "```json", json.dumps(result, sort_keys=True, indent=2), "```", ""]
        )
    lines.extend(
        [
            "## Method and limitations",
            "",
            *[f"- {limit}" for limit in report["limitations"]],
            "",
            "Full metrics, probability applicability, denominators, model versions, parameters, source hashes and uncertainty are in report.json.",
            "Hardware, model-training dependencies and private label-adjudication artifacts must be retained in the restricted study archive.",
            "",
        ]
    )
    return "\n".join(lines)


def render_csv(report):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "experiment_id",
            "variant",
            "status",
            "cohort_n",
            "coverage",
            "accuracy",
            "end_to_end_accuracy",
            "precision",
            "recall",
            "f1",
            "macro_f1",
            "weighted_f1",
        ]
    )
    for variant, result in report["variants"].items():
        metrics = result.get("metrics") or {}
        writer.writerow(
            [
                report["experiment_id"],
                variant,
                result["status"],
                result["cohort_sample_count"],
                *[
                    metrics.get(k, "")
                    for k in (
                        "coverage",
                        "accuracy",
                        "end_to_end_accuracy",
                        "precision",
                        "recall",
                        "f1",
                        "macro_f1",
                        "weighted_f1",
                    )
                ],
            ]
        )
    return buffer.getvalue()


def write_report(report, output_root):
    """A new experiment directory is required; an existing result cannot be overwritten."""
    import re

    identifier = report["experiment_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identifier):
        raise ValueError("Invalid experiment identifier")
    texts = {
        "report.json": json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
        "report.md": render_markdown(report),
        "metrics.csv": render_csv(report),
        "report.sha256": canonical_digest(report) + "\n",
    }
    folder = Path(output_root) / identifier
    folder.mkdir(parents=True, exist_ok=False)
    for name, content in texts.items():
        with (folder / name).open("x", encoding="utf-8", newline="") as target:
            target.write(content)
    return folder
