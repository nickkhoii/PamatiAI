from copy import deepcopy

from ai.visual.features import frame_quality
from ai.visual.files import temporary_frames
from ai.visual.normalization import normalize, normalize_features
from ai.visual.sampling import VERSION as SAMPLING_VERSION
from ai.visual.sampling import sample_frames
from ai.visual.validation import (
    MAX_BYTES,
    MAX_INPUT_FRAMES,
    MAX_PIXELS,
    MAX_SECONDS,
    EncodedFrame,
    decode_frame,
    validate_frames,
)


class VisualInferenceService:
    def __init__(self, extractor, model, *, temporary_directory=None, sample_count=8,
                 minimum_confidence=0.0, max_bytes=MAX_BYTES, max_pixels=MAX_PIXELS,
                 max_frames=MAX_INPUT_FRAMES, max_seconds=MAX_SECONDS):
        self.extractor, self.model = extractor, model
        self.temporary_directory, self.sample_count = temporary_directory, sample_count
        self.minimum_confidence = minimum_confidence
        self.limits = {"max_bytes": max_bytes, "max_pixels": max_pixels,
                       "max_frames": max_frames, "max_seconds": max_seconds}

    def analyze_frames(self, encoded_frames):
        validated = validate_frames(encoded_frames, **self.limits)
        selected, indices = sample_frames(validated, self.sample_count)
        with temporary_frames(selected, self.temporary_directory) as paths:
            frames = tuple(decode_frame(EncodedFrame(path.read_bytes(), source.timestamp_seconds))
                           for path, source in zip(paths, selected, strict=True))
            quality = frame_quality(frames)
            features = self.extractor.extract(frames)
            normalize_features(features)  # Reject identity/attribute/diagnostic feature keys before model work.
            output = self.model.predict(deepcopy(features))
            return normalize(
                features, output, quality=quality,
                sampling={"version": SAMPLING_VERSION, "input_frame_count": len(validated),
                          "sampled_frame_count": len(selected), "indices": list(indices),
                          "timestamps_seconds": [frame.timestamp_seconds for frame in frames],
                          "timing_source": "uploader_declared_not_verified"},
                feature_metadata=self.extractor.metadata, model_metadata=self.model.metadata,
                minimum_confidence=self.minimum_confidence,
            )
