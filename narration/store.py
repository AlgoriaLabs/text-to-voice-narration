"""Where finished narrations live until they expire.

- data/audio/<random id>.<ext>: the audio files. Only this folder is public, at {AUDIO_BASE_URL}/<file>. The ids are
  random (144 bits), so a link can't be guessed from a job id.
- data/narrations/<sha256>.json: the answer given for a job, keyed by the gateway's Idempotency-Key (the job id), so
  a job the gateway runs again after a restart gets the same file instead of a second synthesis.

Files are kept for `retention_seconds` after they are made. Provider Standard v1 [S8] wants URLs in an output to stay
valid for the jobs' retentionSeconds (24 hours by default), so the default here is 25 hours.
"""

import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

FILE_NAME = re.compile(r"^[A-Za-z0-9_-]{16,64}\.(mp3|ogg|wav)$")


class NarrationStore:
    def __init__(self, data_dir: str | Path, retention_seconds: int):
        self.audio_dir = Path(data_dir) / "audio"
        self.index_dir = Path(data_dir) / "narrations"
        self.retention_seconds = retention_seconds
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    @staticmethod
    def key(idempotency_key: str, tier: str, request: dict) -> str:
        body = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(f"{idempotency_key}\n{tier}\n{body}".encode()).hexdigest()

    @contextmanager
    def lock(self, key: str):
        """Holds one job's work, so two calls with the same key never synthesize twice at once."""
        with self._locks_guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            yield

    def find(self, key: str) -> dict | None:
        """The answer stored for this key, if its audio file is still there."""
        path = self.index_dir / f"{key}.json"
        try:
            entry = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return None
        if not (self.audio_dir / entry.get("file", "")).is_file():
            return None
        return entry.get("output")

    def save_audio(self, data: bytes, extension: str) -> tuple[str, float]:
        """Writes the file atomically under a new random name. Returns the name and when it expires (epoch)."""
        name = f"{secrets.token_urlsafe(18)}.{extension}"
        _write_atomic(self.audio_dir / name, data)
        return name, time.time() + self.retention_seconds

    def remember(self, key: str, file_name: str, output: dict) -> None:
        entry = {"file": file_name, "output": output, "created": time.time()}
        _write_atomic(self.index_dir / f"{key}.json", json.dumps(entry).encode())

    def audio_path(self, name: str) -> Path | None:
        if not FILE_NAME.match(name):
            return None
        path = self.audio_dir / name
        return path if path.is_file() else None

    def cleanup(self, now: float | None = None) -> int:
        """Deletes expired audio files and answers. Returns how many files went."""
        cutoff = (now or time.time()) - self.retention_seconds
        removed = 0
        for folder in (self.audio_dir, self.index_dir):
            for path in folder.iterdir():
                try:
                    if path.is_file() and path.stat().st_mtime < cutoff:
                        path.unlink()
                        removed += 1
                except FileNotFoundError:
                    pass
        with self._locks_guard:
            for key in [k for k, lock in self._locks.items() if not lock.locked()]:
                del self._locks[key]
        return removed


def _write_atomic(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
