from ai.audio.normalization import EMOTIONS
from ai.text.confidence import probabilities
from ai.visual.normalization import EXPRESSIONS

LABELS = {
    "text_sentiment": {"positive", "negative", "neutral", "mixed"},
    "modeled_affect": EMOTIONS,
    "observed_expression": EXPRESSIONS,
}


def source_channels(observation):
    output = observation.output
    channels = []
    if observation.modality == "text" and output.get("sentiment_probabilities") is not None:
        channels.append(("text_sentiment", "exclusive", output["sentiment_probabilities"]))
    if observation.modality in {"text", "audio"} and output.get("emotion_probabilities") is not None:
        channels.append(("modeled_affect", output.get("emotion_probability_kind"), output["emotion_probabilities"]))
    if observation.modality == "visual" and output.get("expression_probabilities") is not None:
        channels.append(("observed_expression", output.get("probability_kind"), output["expression_probabilities"]))
    result = []
    for target, kind, values in channels:
        if kind not in {"exclusive", "independent"} or not isinstance(values, dict) or values.keys() - LABELS[target]:
            raise ValueError("Unsupported source probability semantics")
        normalized = probabilities(values, distribution=kind == "exclusive")
        result.append((target, kind, normalized))
    return result
