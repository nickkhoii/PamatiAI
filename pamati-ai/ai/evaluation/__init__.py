"""Research evaluation is offline; it never treats AI observations as ground truth."""

from ai.evaluation.contracts import NOT_EVALUATED, DatasetSpec, ExperimentSpec, Prediction, Sample

__all__ = ["NOT_EVALUATED", "DatasetSpec", "ExperimentSpec", "Prediction", "Sample"]
