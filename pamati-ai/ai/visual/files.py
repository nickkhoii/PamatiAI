import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def temporary_frames(frames, directory=None):
    root = None
    if directory:
        root = Path(directory).absolute()
        if root.is_symlink():
            raise ValueError("Visual temporary root must not be a symlink")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pamati-visual-", dir=root) as folder:
        paths = []
        for index, frame in enumerate(frames):
            # No client names, paths, URLs or archive extraction.
            path = Path(folder) / f"frame-{index}.bmp"
            with path.open("xb") as stream:
                os.chmod(path, 0o600)
                stream.write(frame.data)
            paths.append(path)
        yield tuple(paths)
    # All sampled temporary media is removed on normal exit, including model failures.
