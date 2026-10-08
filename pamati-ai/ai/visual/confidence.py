from ai.text.confidence import bounded, probabilities, uncertainty


def normalize_confidence(output, minimum_confidence):
    bounded(minimum_confidence)
    if output.probability_kind not in {None, "exclusive", "independent"}:
        raise ValueError("Unsupported expression probability semantics")
    if output.expression_probabilities is not None and output.probability_kind is None:
        raise ValueError("Declare expression probability semantics")
    values = probabilities(output.expression_probabilities, distribution=output.probability_kind == "exclusive")
    confidence = bounded(output.confidence) if output.confidence is not None else None
    if confidence is not None and (not isinstance(output.confidence_method, str)
                                   or not output.confidence_method or len(output.confidence_method) > 120):
        raise ValueError("Confidence requires a declared method")
    info = uncertainty(values if output.probability_kind == "exclusive" else None)
    if info["method"] != "unavailable":
        info["method"] = "normalized_observed_expression_entropy"
    info.update(confidence_method=output.confidence_method, minimum_confidence=minimum_confidence)
    abstained = output.abstained or (minimum_confidence > 0 and (
        confidence is None or confidence < minimum_confidence
    ))
    return values, confidence, info, abstained
