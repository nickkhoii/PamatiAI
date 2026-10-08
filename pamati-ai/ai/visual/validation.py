"""Strict, bounded decoding of uncompressed 24-bit BMP research frames."""

import math
import struct
from dataclasses import dataclass

VERSION = "bmp24-validation-v1"
MAX_BYTES = 3_000_000
MAX_INPUT_FRAMES = 32
MAX_PIXELS = 262_144
MAX_SECONDS = 30.0


class InvalidVisualInput(ValueError):
    pass


@dataclass(frozen=True)
class EncodedFrame:
    data: bytes
    timestamp_seconds: float = 0.0


@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    rgb: bytes
    timestamp_seconds: float


def dimensions(data, *, max_pixels=MAX_PIXELS):
    if len(data) < 54 or data[:2] != b"BM":
        raise InvalidVisualInput("Use an uncompressed 24-bit BMP frame")
    size, reserved1, reserved2, offset = struct.unpack_from("<IHHI", data, 2)
    header, width, height, planes, bits, compression, payload_size = struct.unpack_from("<IiiHHII", data, 14)
    if (size != len(data) or reserved1 or reserved2 or offset != 54 or header != 40
            or planes != 1 or bits != 24 or compression != 0):
        raise InvalidVisualInput("Unsupported BMP encoding or invalid container")
    if not (1 <= width <= 1024 and 1 <= abs(height) <= 1024 and width * abs(height) <= max_pixels):
        raise InvalidVisualInput("Frame dimensions exceed the configured bound")
    stride = ((width * 3 + 3) // 4) * 4
    expected = stride * abs(height)
    if payload_size not in {0, expected} or len(data) != offset + expected:
        raise InvalidVisualInput("Incomplete or inconsistent BMP pixels")
    return width, height, stride


def validate_frames(frames, *, max_bytes=MAX_BYTES, max_pixels=MAX_PIXELS,
                    max_frames=MAX_INPUT_FRAMES, max_seconds=MAX_SECONDS):
    if not isinstance(frames, (tuple, list)) or not 1 <= len(frames) <= max_frames:
        raise InvalidVisualInput("Supply a bounded nonempty frame sequence")
    if any(not isinstance(frame, EncodedFrame) or not isinstance(frame.data, bytes) for frame in frames):
        raise InvalidVisualInput("Supply encoded byte frames only")
    if sum(len(frame.data) for frame in frames) > max_bytes:
        raise InvalidVisualInput("Visual input exceeds the byte limit")
    previous = None
    for frame in frames:
        time = frame.timestamp_seconds
        if (isinstance(time, bool) or not isinstance(time, (int, float)) or not math.isfinite(time)
                or not 0 <= time <= max_seconds or (previous is not None and time <= previous)):
            raise InvalidVisualInput("Frame timestamps must be finite, increasing and within the duration limit")
        dimensions(frame.data, max_pixels=max_pixels)
        previous = time
    return tuple(frames)


def decode_frame(encoded: EncodedFrame) -> Frame:
    width, height, stride = dimensions(encoded.data)
    rows = range(abs(height) - 1, -1, -1) if height > 0 else range(abs(height))
    rgb = bytearray()
    for row in rows:
        start = 54 + row * stride
        for col in range(width):
            pixel = start + col * 3
            rgb.extend(encoded.data[pixel:pixel + 3][::-1])
    return Frame(width, abs(height), bytes(rgb), float(encoded.timestamp_seconds))
