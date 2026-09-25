"""One trusted PCK digest per native worker pool, guarded by file metadata."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

ENV_NAME = "STS2_NATIVE_PCK_FINGERPRINT"
_UNIX_EPOCH_TICKS = 621355968000000000


def _identity(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


@dataclass(frozen=True)
class PckFingerprint:
    path: Path
    sha256: str
    file_id: int
    size: int
    mtime_ns: int
    ctime_ns: int
    seconds: float

    @classmethod
    def measure_for_assembly(cls, assembly: str | Path) -> PckFingerprint:
        return cls.measure(Path(assembly).resolve().parent.parent / "SlayTheSpire2.pck")

    @classmethod
    def measure(cls, path: Path) -> PckFingerprint:
        path = path.resolve()
        before = _identity(path)
        started = time.monotonic()
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        seconds = time.monotonic() - started
        if _identity(path) != before:
            raise RuntimeError(f"PCK changed while fingerprinting: {path}")
        return cls(path, digest.hexdigest().upper(), *before, seconds)

    def is_current(self) -> bool:
        return _identity(self.path) == (self.file_id, self.size, self.mtime_ns, self.ctime_ns)

    def worker_hint(self) -> str:
        # The hint is only used on Windows: Python's ctime is the creation time there.
        # Other hosts keep the worker's existing independent hash path.
        return json.dumps({
            "path": str(self.path), "sha256": self.sha256, "file_id": self.file_id,
            "size": self.size,
            "mtime_ticks": _UNIX_EPOCH_TICKS + self.mtime_ns // 100,
            "ctime_ticks": _UNIX_EPOCH_TICKS + self.ctime_ns // 100,
        }) if os.name == "nt" else ""
