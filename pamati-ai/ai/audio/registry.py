from ai.audio.interface import AudioModelMetadata, AudioModelOutput


class FeaturesOnly:
    metadata = AudioModelMetadata(
        "acoustic-features", "1", "1",
        limitations=("Acoustic comparator only; no emotion model or speech recognizer.",),
    )

    def predict(self, sample, features):
        return AudioModelOutput()


class AudioModelRegistry:
    def __init__(self):
        self._factories = {}

    def register(self, name, factory):
        if not name or name in self._factories:
            raise ValueError("Empty or duplicate audio model registration")
        self._factories[name] = factory

    def resolve(self, name):
        if name not in self._factories:
            raise ValueError("Unknown audio model")
        model = self._factories[name]()
        if not all((model.metadata.identifier, model.metadata.version, model.metadata.adapter_version)):
            raise ValueError("Audio model provenance is required")
        return model


registry = AudioModelRegistry()
registry.register("acoustic-features", FeaturesOnly)
