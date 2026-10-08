from collections.abc import Callable

from ai.text.baseline import LexiconBaseline
from ai.text.interface import TextModel


class ModelRegistry:
    def __init__(self):
        self._factories: dict[str, Callable[[], TextModel]] = {}

    def register(self, name: str, factory: Callable[[], TextModel]):
        if not name or name in self._factories:
            raise ValueError("Empty or duplicate model registration")
        self._factories[name] = factory

    def resolve(self, name: str) -> TextModel:
        if name not in self._factories:
            raise ValueError("Unknown text-analysis model")
        model = self._factories[name]()
        metadata = model.metadata
        if not metadata.identifier or not metadata.version or not metadata.adapter_version:
            raise ValueError("Model provenance is required")
        return model


registry = ModelRegistry()
registry.register("lexicon-baseline", LexiconBaseline)
