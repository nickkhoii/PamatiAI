from copy import deepcopy

from ai.audio.features import extract_features
from ai.audio.files import temporary_audio
from ai.audio.normalization import normalize
from ai.audio.validation import MAX_BYTES, MAX_SECONDS, InvalidAudio, validate_audio


class AudioInferenceService:
    def __init__(self, model, *, minimum_confidence=0.0, temporary_directory=None,
                 max_bytes=MAX_BYTES, max_seconds=MAX_SECONDS):
        self.model = model
        self.minimum_confidence = minimum_confidence
        self.temporary_directory = temporary_directory
        self.max_bytes, self.max_seconds = max_bytes, max_seconds

    def analyze_bytes(self, data):
        # The backend must authorize before invoking this pure computation service.
        if not data or len(data) > self.max_bytes:
            raise InvalidAudio("Audio is empty or exceeds the upload limit")
        with temporary_audio(data, self.temporary_directory) as path:
            sample = validate_audio(path.read_bytes(), max_bytes=self.max_bytes,
                                    max_seconds=self.max_seconds)
            features = extract_features(sample)
            output = self.model.predict(sample, deepcopy(features))
            return normalize(features, output, minimum_confidence=self.minimum_confidence,
                             limitations=self.model.metadata.limitations)
