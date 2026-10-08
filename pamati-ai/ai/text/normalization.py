from dataclasses import dataclass

from ai.text.confidence import bounded, probabilities, uncertainty
from ai.text.interface import ModelOutput

LIMITATIONS = (
    "Research estimate, not a clinical assessment or diagnosis.",
    "Sarcasm, multilingual/code-switched language, cultural context and domain shift may reduce accuracy.",
    "Confidence and probabilities are not calibrated clinical certainty.",
)


@dataclass(frozen=True)
class NormalizedResult:
    labels: dict
    confidence: float | None
    uncertainty: dict
    uncertainty_method: str
    language: str | None
    abstained: bool
    limitations: tuple[str, ...]


def normalize(output: ModelOutput, *, language=None, limitations=(), minimum_confidence=0.0):
    bounded(minimum_confidence)
    sentiment = probabilities(output.sentiment_probabilities, distribution=True)
    if output.emotion_probabilities is not None and output.emotion_probability_kind not in {
        "exclusive", "independent"
    }:
        raise ValueError("Emotion probabilities require declared semantics")
    emotions = probabilities(
        output.emotion_probabilities, distribution=output.emotion_probability_kind == "exclusive"
    )
    polarity = bounded(output.polarity, -1, 1) if output.polarity is not None else None
    if output.category is not None and output.category not in {"positive", "negative", "neutral", "mixed"}:
        raise ValueError("Unsupported normalized category")
    confidence = bounded(output.confidence) if output.confidence is not None else None
    if confidence is not None and not output.confidence_method:
        raise ValueError("Confidence requires a method")
    abstained = output.abstained or (minimum_confidence > 0 and (
        confidence is None or confidence < minimum_confidence
    )) or (polarity is None and output.category is None and sentiment is None and emotions is None)
    info = uncertainty(sentiment)
    info["confidence_method"] = output.confidence_method
    info["minimum_confidence"] = minimum_confidence
    return NormalizedResult(
        labels={
            "schema_version": "1", "sentiment_polarity": polarity,
            "sentiment_category": output.category, "sentiment_probabilities": sentiment,
            "emotion_probabilities": emotions,
            "emotion_probability_kind": output.emotion_probability_kind,
            "interpretation": "research_estimate", "abstained": abstained,
        },
        confidence=confidence, uncertainty=info, uncertainty_method=info["method"],
        language=language, abstained=abstained,
        limitations=tuple(dict.fromkeys((*LIMITATIONS, *limitations, *output.limitations))),
    )
