import json
import math
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime

from ai.multimodal.channels import LABELS, source_channels
from ai.multimodal.confidence import channel_uncertainty, fusion_confidence, validate_channel
from ai.multimodal.interface import MODALITIES, FusionConfig
from ai.text.confidence import bounded

VERSION = "multimodal-observation-v1"
LIMITATIONS = (
    "Experimental research fusion; not empirically validated or a clinical assessment.",
    "Missing/refused/failed modalities are not evidence of neutrality, health or pathology.",
    "Observable visual expression is not a direct measure of internal emotion or mental state.",
    "More modalities do not guarantee better accuracy; correlated errors and domain shift remain possible.",
)


def validate_config(config):
    bounded(config.minimum_confidence)
    if (config.weights.keys() - set(MODALITIES) or not config.weights
            or any(isinstance(w, bool) or not isinstance(w, (int, float))
                   or not math.isfinite(w) or not 0 <= w <= 1000 for w in config.weights.values())
            or not any(w > 0 for w in config.weights.values())):
        raise ValueError("Use finite nonnegative experimental modality weights, with at least one positive weight")
    bounded(config.maximum_source_span_seconds, 0, 3600)


class NormalizedFusionResult:
    def __init__(self, labels, confidence, info, abstained):
        self.labels, self.confidence, self.uncertainty = labels, confidence, info
        self.uncertainty_method = info["method"]
        self.abstained = abstained
        self.limitations = tuple(labels["limitations"])
        self.source_inference_ids = tuple(labels["source_inference_ids"])


class FusionService:
    def __init__(self, strategy, config=None):
        self.strategy, self.config = strategy, deepcopy(config) if config is not None else FusionConfig()
        validate_config(self.config)

    def fuse(self, observations, *, consented_modalities=MODALITIES, excluded=None, timestamp=None):
        if set(consented_modalities) - set(MODALITIES):
            raise ValueError("Unknown consent modality")
        if len(observations) > 3 or any(o.modality not in MODALITIES for o in observations):
            raise ValueError("Supply at most one source per supported modality")
        if len({o.modality for o in observations}) != len(observations):
            raise ValueError("Choose one source per modality for this experiment")
        if len({o.source_id for o in observations}) != len(observations):
            raise ValueError("Source identifiers must be distinct")
        reasons = dict(excluded or {})
        sources = []
        for observation in sorted(observations, key=lambda o: MODALITIES.index(o.modality)):
            if observation.modality not in consented_modalities:
                reasons[observation.modality] = "unconsented"
            elif observation.status != "completed":
                reasons[observation.modality] = observation.status
            elif not observation.output or observation.output.get("abstained", False):
                reasons[observation.modality] = "abstained_or_missing_analysis"
            else:
                try:
                    if len(json.dumps(observation.output, allow_nan=False)) > 65536:
                        raise ValueError("Source output exceeds the summary limit")
                    source_channels(observation)
                    parsed = datetime.fromisoformat(observation.timestamp)
                    if parsed.tzinfo is None:
                        raise ValueError("Source timestamps require a timezone")
                    if observation.confidence is not None:
                        bounded(observation.confidence)
                except (TypeError, ValueError):
                    reasons[observation.modality] = "invalid_output"
                    continue
                sources.append(deepcopy(observation))
        if sources:
            newest = max(datetime.fromisoformat(s.timestamp) for s in sources)
            retained = []
            for source in sources:
                if (newest - datetime.fromisoformat(source.timestamp)).total_seconds() > self.config.maximum_source_span_seconds:
                    reasons[source.modality] = "out_of_alignment_window"
                else:
                    retained.append(source)
            sources = retained
        available = [source.modality for source in sources]
        missing = [m for m in MODALITIES if m not in available]
        for modality in missing:
            reasons.setdefault(modality, "unconsented" if modality not in consented_modalities else "unavailable")
        output = self.strategy.fuse(tuple(deepcopy(sources)), deepcopy(self.config)) if sources else None
        channels, uncertainty = [], []
        by_id = {source.source_id: source for source in sources}
        if output:
            for channel in output.channels:
                if (channel.target not in LABELS or channel.probabilities.keys() - LABELS[channel.target]
                        or not channel.source_ids or len(set(channel.source_ids)) != len(channel.source_ids)
                        or set(channel.source_ids) - by_id.keys()):
                    raise ValueError("Fusion output must reference available, consented sources and supported targets")
                # A learned adapter cannot turn visual expression into internal affect.
                allowed = {"text_sentiment": {"text"}, "modeled_affect": {"text", "audio"},
                           "observed_expression": {"visual"}}[channel.target]
                if any(by_id[s].modality not in allowed for s in channel.source_ids):
                    raise ValueError("Source modality cannot establish this target")
                if channel.effective_weights:
                    if set(channel.effective_weights) != set(channel.source_ids):
                        raise ValueError("Effective weights must identify every participant")
                    for weight in channel.effective_weights.values():
                        bounded(weight)
                    if not math.isclose(sum(channel.effective_weights.values()), 1.0):
                        raise ValueError("Effective weights must sum to one")
                values = validate_channel(channel)
                channels.append({**asdict(channel), "probabilities": values,
                                 "source_ids": list(channel.source_ids)})
                uncertainty.append(channel_uncertainty(channel, by_id))
            confidence, abstained = fusion_confidence(output, self.config.minimum_confidence)
        else:
            confidence, abstained = None, True
        now = timestamp or datetime.now(UTC).isoformat()
        info = {"method": "per_probability_channel_entropy" if uncertainty else "unavailable",
                "channels": uncertainty, "calibrated": False,
                "confidence_method": output.confidence_method if output else None,
                "missing_modalities": missing, "missingness_adjustment": "not_validated"}
        limitations = tuple(dict.fromkeys((*LIMITATIONS, *(output.limitations if output else ()),
                                           *(limit for source in sources for limit in source.limitations))))
        labels = {
            "schema_version": VERSION, "experimental": True, "empirically_validated": False,
            "interpretation": "research_observation", "available_modalities": available,
            "missing_modalities": missing, "excluded_modalities": reasons,
            "individual_modality_outputs": {source.modality: asdict(source) for source in sources},
            "fusion_method": self.strategy.metadata.identifier,
            "fusion_version": self.strategy.metadata.version,
            "fusion_strategy_metadata": asdict(self.strategy.metadata),
            "fusion_configuration": asdict(self.config),
            "combined_output": {"probability_channels": channels,
                                "observation_modalities": available, "universal_affect_score": None},
            "confidence": confidence, "uncertainty": info,
            "source_inference_ids": [source.source_id for source in sources],
            "model_versions": {source.modality: {"identifier": source.model_identifier, "version": source.model_version}
                               for source in sources},
            "timestamp": now, "abstained": abstained, "limitations": list(limitations),
        }
        return NormalizedFusionResult(labels, confidence, info, abstained)
