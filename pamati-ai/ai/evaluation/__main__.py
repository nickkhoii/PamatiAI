"""Run from pamati-ai: python -m ai.evaluation MANIFEST --output DIR."""

import argparse

from ai.evaluation.experiments import run_manifest
from ai.evaluation.reports import write_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--text-model", help="Explicit registered text model; does not download datasets or models"
    )
    args = parser.parse_args()
    try:
        predictors = None
        if args.text_model:
            from ai.evaluation.adapters import RegisteredTextPredictor

            predictors = {"text_only": RegisteredTextPredictor(args.text_model)}
        report = run_manifest(args.manifest, predictors=predictors)
        folder = write_report(report, args.output)
    except FileExistsError:
        parser.exit(2, "Experiment output already exists; choose a new experiment ID.\n")
    except (ValueError, OSError):
        parser.exit(
            2,
            "Evaluation failed: invalid or unavailable private inputs; inspect configuration locally.\n",
        )
    print(report["status"])
    print(f"Aggregate experiment artifacts written to {folder.name}.")


if __name__ == "__main__":
    main()
