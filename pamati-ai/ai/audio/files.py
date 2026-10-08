"""Server-generated file names only; callers never supply filesystem paths."""

import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


def private_root(directory):
    root = Path(directory).absolute()
    if root.is_symlink():
        raise ValueError("Audio storage root must not be a symlink")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root.resolve()


@contextmanager
def temporary_audio(data: bytes, directory=None):
    root = private_root(directory) if directory else None
    with tempfile.TemporaryDirectory(prefix="pamati-audio-", dir=root) as folder:
        path = Path(folder) / "input.wav"
        with path.open("xb") as stream:
            os.chmod(path, 0o600)
            stream.write(data)
        yield path
    # TemporaryDirectory removes the file on success, decoding failure, and model failure.


class RecordingStore:
    def __init__(self, directory):
        self.root = private_root(directory)

    def new_key(self):
        return f"{uuid4().hex}.wav"

    def _path(self, key):
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{32}\.wav", key):
            raise ValueError("Invalid recording reference")
        path = self.root / key
        if path.is_symlink():
            raise ValueError("Recording references must not be symlinks")
        return path

    def write(self, key, data):
        path = self._path(key)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def delete(self, key):
        self._path(key).unlink(missing_ok=True)
