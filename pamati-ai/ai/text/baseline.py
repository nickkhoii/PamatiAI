import re

from ai.text.interface import ModelMetadata, ModelOutput


class LexiconBaseline:
    """Small, unvalidated English comparator. Unknown vocabulary causes abstention."""

    positive = frozenset({"happy", "good", "great", "love", "hopeful", "calm", "grateful"})
    negative = frozenset({"sad", "bad", "hate", "angry", "stressed", "afraid", "worried"})
    metadata = ModelMetadata(
        "lexicon-baseline", "1", "1",
        configuration={"positive": sorted(positive), "negative": sorted(negative)},
        limitations=("Unvalidated English lexicon; ignores negation and context; no emotion probabilities.",),
    )

    def predict(self, sample):
        tokens = re.findall(r"\b\w+\b", sample.text.casefold())
        pos = sum(t in self.positive for t in tokens)
        neg = sum(t in self.negative for t in tokens)
        if not pos + neg:
            return ModelOutput(abstained=True, limitations=("No supported sentiment evidence.",))
        polarity = (pos - neg) / (pos + neg)
        category = "mixed" if pos and neg else "positive" if pos else "negative"
        return ModelOutput(polarity=polarity, category=category)
