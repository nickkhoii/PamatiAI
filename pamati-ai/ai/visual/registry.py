from ai.visual.features import NoExpressionExtractor
from ai.visual.interface import VisualMetadata, VisualModelOutput


class NoExpressionModel:
    metadata = VisualMetadata(
        "no-expression-model", "1",
        limitations=("No expression model is deployed; affect inference is unavailable.",),
    )

    def predict(self, features):
        return VisualModelOutput(abstained=True)


class VisualRegistry:
    def __init__(self):
        self._factories = {}

    def register(self, name, factory):
        if not name or name in self._factories:
            raise ValueError("Empty or duplicate visual adapter registration")
        self._factories[name] = factory

    def resolve(self, name):
        if name not in self._factories:
            raise ValueError("Unknown visual adapter")
        adapter = self._factories[name]()
        if not adapter.metadata.identifier or not adapter.metadata.version:
            raise ValueError("Versioned visual adapter provenance is required")
        return adapter


extractors = VisualRegistry()
models = VisualRegistry()
extractors.register("no-expression", NoExpressionExtractor)
models.register("no-expression", NoExpressionModel)
