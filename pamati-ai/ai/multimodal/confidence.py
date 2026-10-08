from ai.text.confidence import bounded, probabilities, uncertainty


def channel_uncertainty(channel, sources):
    info = uncertainty(channel.probabilities if channel.probability_kind == "exclusive" else None)
    if info["method"] != "unavailable":
        info["method"] = "normalized_probability_entropy"
    info["target"] = channel.target
    info["source_ids"] = list(channel.source_ids)
    info["independence_assumed"] = False
    return info


def validate_channel(channel):
    if channel.probability_kind not in {"exclusive", "independent"}:
        raise ValueError("Invalid fusion probability semantics")
    return probabilities(channel.probabilities, distribution=channel.probability_kind == "exclusive")


def fusion_confidence(output, minimum_confidence):
    confidence = bounded(output.confidence) if output.confidence is not None else None
    if confidence is not None and (not isinstance(output.confidence_method, str) or not output.confidence_method):
        raise ValueError("Fusion confidence requires a declared method")
    abstained = output.abstained or (minimum_confidence > 0 and (
        confidence is None or confidence < minimum_confidence
    ))
    return confidence, abstained
