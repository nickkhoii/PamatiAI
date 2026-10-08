from dataclasses import dataclass

from ai.text.confidence import bounded
from ai.visual.confidence import normalize_confidence

VERSION = "observable-expression-schema-v1"
ACTION_UNITS = {"AU01", "AU02", "AU04", "AU05", "AU06", "AU07", "AU09", "AU10",
               "AU12", "AU14", "AU15", "AU17", "AU20", "AU23", "AU24", "AU25", "AU26", "AU45"}
MEASUREMENTS = {"mouth_openness", "brow_raise", "lip_corner_raise", "eye_closure"}
EXPRESSIONS = {"smiling", "frowning", "brow_raised", "mouth_open", "eyes_closed", "no_clear_expression"}
LIMITATIONS = (
    "Observed expression estimates do not establish internal emotion, intent or mental state.",
    "Not facial recognition, student identification, protected-attribute inference or psychiatric diagnosis.",
    "Lighting, camera angle, occlusion, context, cultural variation and individual differences affect results.",
    "Disability and atypical expression must not be treated as evidence of pathology.",
    "Confidence and probability spread are uncalibrated, not clinical certainty.",
)


def observation_map(values, allowed, upper=1.0):
    if values is None:
        return None
    if not isinstance(values, dict) or not values or values.keys() - allowed:
        raise ValueError("Only declared observable expression measurements are supported")
    return {key: bounded(value, 0, upper) for key, value in values.items()}


def normalize_features(features):
    return {
        "action_unit_intensities": observation_map(features.action_unit_intensities, ACTION_UNITS, 5.0),
        "action_unit_scale": "0_to_5_estimated_intensity",
        "expression_measurements": observation_map(features.expression_measurements, MEASUREMENTS),
        "expression_measurement_scale": "0_to_1_adapter_defined",
    }


@dataclass(frozen=True)
class NormalizedVisualResult:
    labels: dict
    sampled_frame_count: int
    confidence: float | None
    uncertainty: dict
    uncertainty_method: str
    abstained: bool
    limitations: tuple[str, ...]


def normalize(features, output, *, quality, sampling, feature_metadata, model_metadata,
              minimum_confidence=0.0):
    observations = normalize_features(features)
    if output.expression_probabilities is not None and output.expression_probabilities.keys() - EXPRESSIONS:
        raise ValueError("Map model outputs to observed expression classes, not internal states or attributes")
    values, confidence, info, abstained = normalize_confidence(output, minimum_confidence)
    if values is None and all(observations[k] is None for k in ("action_unit_intensities", "expression_measurements")):
        abstained = True
    return NormalizedVisualResult(
        labels={"schema_version": VERSION, "interpretation": "observable_expression_research_estimate",
                "internal_state_inference": "not_supported", "features": observations,
                "quality": quality, "sampling": sampling,
                "feature_extractor": {"identifier": feature_metadata.identifier, "version": feature_metadata.version},
                "expression_probabilities": values, "probability_kind": output.probability_kind,
                "abstained": abstained},
        sampled_frame_count=sampling["sampled_frame_count"], confidence=confidence,
        uncertainty=info, uncertainty_method=info["method"], abstained=abstained,
        limitations=tuple(dict.fromkeys((*LIMITATIONS, *feature_metadata.limitations,
                                        *model_metadata.limitations, *output.limitations))),
    )
