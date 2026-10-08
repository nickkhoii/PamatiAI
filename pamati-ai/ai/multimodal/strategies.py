from collections import defaultdict

from ai.multimodal.channels import source_channels
from ai.multimodal.interface import FusionMetadata, FusionOutput, ProbabilityChannel


class LateFusion:
    metadata = FusionMetadata("late-fusion", "1")

    def fuse(self, observations, config):
        # Independent decision outputs are preserved, without a universal affect scalar.
        return FusionOutput(channels=tuple(
            ProbabilityChannel(target, kind, values, (source.source_id,))
            for source in observations for target, kind, values in source_channels(source)
        ))


class WeightedProbabilityFusion:
    metadata = FusionMetadata("weighted-probability", "1")

    def fuse(self, observations, config):
        groups = defaultdict(list)
        for source in observations:
            weight = config.weights.get(source.modality, 0.0)
            if weight <= 0:
                continue
            for target, kind, values in source_channels(source):
                # Different label sets/semantics are separate experiments, never zero-filled.
                groups[(target, kind, tuple(sorted(values)))].append((source, values, weight))
        channels = []
        for (target, kind, labels), members in sorted(groups.items()):
            denominator = sum(weight for _, _, weight in members)
            effective = {source.source_id: weight / denominator for source, _, weight in members}
            values = {label: sum(probs[label] * effective[source.source_id]
                                 for source, probs, _ in members) for label in labels}
            channels.append(ProbabilityChannel(target, kind, values,
                                                tuple(source.source_id for source, _, _ in members), effective))
        return FusionOutput(channels=tuple(channels), limitations=(
            "Configured weights, including equal weights, are arbitrary experimental parameters, not validated reliability.",
        ))
