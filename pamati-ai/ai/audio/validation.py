"""Bounded decoding of a deliberately narrow, uncompressed audio format."""

import io
import struct
import wave
from dataclasses import dataclass

VERSION = "pcm-wav-validation-v1"
MAX_BYTES = 3_000_000
MAX_SECONDS = 30.0


class InvalidAudio(ValueError):
    pass


@dataclass(frozen=True)
class AudioInput:
    samples: tuple[float, ...]
    sample_rate: int
    duration_seconds: float


def validate_audio(data: bytes, *, max_bytes=MAX_BYTES, max_seconds=MAX_SECONDS) -> AudioInput:
    if not data or len(data) > max_bytes:
        raise InvalidAudio("Audio is empty or exceeds the upload limit")
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise InvalidAudio("Only PCM WAV audio is supported")
    if int.from_bytes(data[4:8], "little") + 8 != len(data):
        raise InvalidAudio("Invalid WAV container length")
    try:
        with wave.open(io.BytesIO(data), "rb") as recording:
            rate, frames = recording.getframerate(), recording.getnframes()
            if (recording.getnchannels() != 1 or recording.getsampwidth() != 2
                    or recording.getcomptype() != "NONE" or not 8000 <= rate <= 48000):
                raise InvalidAudio("Use mono, 16-bit PCM WAV at 8–48 kHz")
            duration = frames / rate
            if not frames or not 0.04 <= duration <= max_seconds:
                raise InvalidAudio("Audio duration is outside the supported range")
            raw = recording.readframes(frames)
            if len(raw) != frames * 2:
                raise InvalidAudio("Truncated audio payload")
    except (wave.Error, EOFError, struct.error) as exc:
        raise InvalidAudio("Malformed WAV audio") from exc
    samples = tuple(v[0] / 32768.0 for v in struct.iter_unpack("<h", raw))
    return AudioInput(samples, rate, duration)
