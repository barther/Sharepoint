"""Filesystem walking, stat collection, and SHA-256 hashing."""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

_HASH_CHUNK = 1 << 20  # 1 MiB


@dataclass
class ScannedFile:
    path: Path
    relative_path: str
    size_bytes: int
    mtime_utc: str
    sha256: str | None
    mime_type: str | None

    @property
    def extension(self) -> str:
        return self.path.suffix.lower().lstrip(".")

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def is_empty(self) -> bool:
        return self.size_bytes == 0


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def walk(root: Path) -> Iterator[Path]:
    """Yield every regular file under `root`, sorted for deterministic runs."""
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            yield path


def scan(root: Path) -> Iterator[ScannedFile]:
    """Walk `root`, stat each file, hash it, and yield a ScannedFile."""
    root = root.resolve()
    for path in walk(root):
        stat = path.stat()
        mtime_utc = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        size = stat.st_size
        sha = sha256_of(path) if size > 0 else hashlib.sha256(b"").hexdigest()
        mime, _ = mimetypes.guess_type(path.name)
        yield ScannedFile(
            path=path,
            relative_path=str(path.relative_to(root)),
            size_bytes=size,
            mtime_utc=mtime_utc,
            sha256=sha,
            mime_type=mime,
        )
