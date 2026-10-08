import re

from ai.multimodal.strategies import LateFusion, WeightedProbabilityFusion


class FusionRegistry:
    def __init__(self):
        self._factories = {}

    def register(self, name, factory):
        if not name or name in self._factories:
            raise ValueError("Empty or duplicate fusion strategy registration")
        self._factories[name] = factory

    def resolve(self, name):
        if name not in self._factories:
            raise ValueError("Unknown fusion strategy")
        strategy = self._factories[name]()
        meta = strategy.metadata
        if not meta.identifier or not meta.version:
            raise ValueError("Fusion strategy identity and version are required")
        if meta.learned and (not meta.artifact_sha256 or not re.fullmatch(r"[0-9a-f]{64}", meta.artifact_sha256)):
            raise ValueError("Learned fusion requires a pinned artifact SHA-256")
        return strategy


registry = FusionRegistry()
registry.register("late-fusion", LateFusion)
registry.register("weighted-probability", WeightedProbabilityFusion)
