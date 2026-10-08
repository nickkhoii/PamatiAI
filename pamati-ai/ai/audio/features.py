"""Simple reproducible acoustic summaries, not validated speech or affect recognition."""

import math
from statistics import fmean, pstdev

VERSION = "acoustic-summary-v1"
CONFIGURATION = {
    "frame_seconds": 0.04, "silence_gate_dbfs": -40.0, "minimum_pause_seconds": 0.2,
    "pitch_min_hz": 80.0, "pitch_max_hz": 400.0, "pitch_correlation_gate": 0.6,
}


def summary(values):
    if not values:
        return {"mean": None, "std": None, "min": None, "max": None}
    return {"mean": fmean(values), "std": pstdev(values), "min": min(values), "max": max(values)}


def pitch(frame, sample_rate):
    # Decimation bounds pure-Python work. No anti-aliasing is claimed by this baseline.
    stride = max(1, int(sample_rate / 4000))
    rate = sample_rate / stride
    values = frame[::stride]
    mean = fmean(values)
    values = [v - mean for v in values]
    best_score, best_lag = 0.0, None
    for lag in range(math.ceil(rate / CONFIGURATION["pitch_max_hz"]),
                     min(len(values) // 2, math.floor(rate / CONFIGURATION["pitch_min_hz"])) + 1):
        left, right = values[:-lag], values[lag:]
        denominator = math.sqrt(sum(v * v for v in left) * sum(v * v for v in right))
        score = sum(a * b for a, b in zip(left, right, strict=True)) / denominator if denominator else 0
        if score > best_score + 1e-6:
            best_score, best_lag = score, lag
    if best_lag and best_score >= CONFIGURATION["pitch_correlation_gate"]:
        return rate / best_lag
    return None


def extract_features(sample):
    frame_size = round(sample.sample_rate * CONFIGURATION["frame_seconds"])
    energy, pitches, pauses = [], [], []
    quiet_seconds = run = 0.0
    active_seconds = 0.0
    for start in range(0, len(sample.samples), frame_size):
        frame = sample.samples[start:start + frame_size]
        seconds = len(frame) / sample.sample_rate
        rms = math.sqrt(fmean(v * v for v in frame))
        dbfs = 20 * math.log10(max(rms, 1e-6))
        energy.append(dbfs)
        if dbfs < CONFIGURATION["silence_gate_dbfs"]:
            quiet_seconds += seconds
            run += seconds
        else:
            active_seconds += seconds
            if run + 1e-9 >= CONFIGURATION["minimum_pause_seconds"]:
                pauses.append(run)
            run = 0.0
            if len(frame) == frame_size:
                hz = pitch(frame, sample.sample_rate)
                if hz is not None:
                    pitches.append(hz)
    if run + 1e-9 >= CONFIGURATION["minimum_pause_seconds"]:
        pauses.append(run)
    clipped = sum(abs(v) >= 32767 / 32768 for v in sample.samples)
    return {
        "feature_version": VERSION, "duration_seconds": sample.duration_seconds,
        "speech_rate": {"words_per_minute": None, "method": "unavailable"},
        "pauses": {"count": len(pauses), "duration_seconds": summary(pauses),
                   "quiet_fraction": quiet_seconds / sample.duration_seconds,
                   "method": "energy_gate_including_leading_trailing_silence"},
        "pitch_hz": {**summary(pitches), "method": "decimated_autocorrelation",
                     "periodic_frame_fraction": len(pitches) / len(energy)},
        "energy_dbfs": {**summary(energy), "method": "frame_rms"},
        "prosody": {"pitch_variability_hz": pstdev(pitches) if pitches else None,
                    "energy_variability_db": pstdev(energy),
                    "acoustic_active_seconds": active_seconds},
        "quality": {"clipped_sample_fraction": clipped / len(sample.samples),
                    "speech_detection": "not_supported", "snr_db": None},
    }
