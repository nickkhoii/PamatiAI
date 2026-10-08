from ai.text.interface import ModelOutput
from ai.text.normalization import normalize
from ai.text.preprocessing import preprocess


class InferenceService:
    def __init__(self, model, minimum_confidence=0.0):
        self.model = model
        self.minimum_confidence = minimum_confidence

    def analyze_text(self, text, language=None):
        sample = preprocess(text, language)
        output = self.model.predict(sample) if sample.text else ModelOutput(abstained=True)
        return normalize(
            output, language=sample.language, limitations=self.model.metadata.limitations,
            minimum_confidence=self.minimum_confidence,
        )
