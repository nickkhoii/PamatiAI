import math


def bounded(value, low=0.0, high=1.0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected a numeric score")  # noqa: TRY004 -- invalid adapter output
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Score outside its declared range")
    return float(value)


def probabilities(values, *, distribution):
    if values is None:
        return None
    if not values or any(not isinstance(k, str) or not k or len(k) > 80 for k in values):
        raise ValueError("Invalid probability labels")
    result = {key: bounded(value) for key, value in values.items()}
    if distribution and not math.isclose(sum(result.values()), 1.0, abs_tol=1e-6):
        raise ValueError("Probabilities must sum to one")
    return result


def uncertainty(distribution):
    if distribution is None:
        return {"method": "unavailable", "normalized_entropy": None, "calibrated": False}
    n = len(distribution)
    entropy = -sum(p * math.log(p) for p in distribution.values() if p > 0)
    return {
        "method": "normalized_sentiment_entropy",
        "normalized_entropy": entropy / math.log(n) if n > 1 else 0.0,
        "calibrated": False,
    }
