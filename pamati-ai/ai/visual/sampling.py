VERSION = "uniform-frame-index-v1"


def sample_frames(frames, maximum=8):
    """Deterministic uniform index sampling, retaining endpoints when more than one is requested."""
    if type(maximum) is not int or not 1 <= maximum <= 8:
        raise ValueError("Select between one and eight sampled frames")
    if not frames:
        raise ValueError("Cannot sample an empty sequence")
    count = min(len(frames), maximum)
    indices = [0] if count == 1 else [round(i * (len(frames) - 1) / (count - 1)) for i in range(count)]
    return tuple(frames[i] for i in indices), tuple(indices)
