"""JSON reading and writing for pipeline artifacts.

Writes are atomic. A stage can take minutes, and the live pipeline re-dumps its
transcript after every chunk, so a crash or a Ctrl+C landing mid-write is a
realistic event rather than a theoretical one. Writing in place would leave a
truncated file that still parses as *something*, which a later stage would then
read as a short transcript — a silent data-loss bug. Writing to a temporary file
and renaming means a reader sees either the previous complete version or the new
complete version, never a partial one.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from meeting_assistant.errors import ArtifactError

# Bounded retry for the one case POSIX-semantics replace cannot avoid: a
# reader that opened the target without FILE_SHARE_DELETE (another program, or
# a plain open() elsewhere). Readers hold artifacts for milliseconds; ~2.5 s
# total is far longer than that and short enough not to stall a stage.
_REPLACE_ATTEMPTS = 8
_REPLACE_FIRST_DELAY_SEC = 0.01

# Flipped off for the rest of the process the first time the filesystem
# reports it cannot do a POSIX-semantics rename (FAT, some network shares).
_posix_replace_supported = sys.platform == "win32"


def _replace_once(src: Path, dst: Path) -> None:
    global _posix_replace_supported
    if _posix_replace_supported:
        from meeting_assistant import _win_fileio

        try:
            _win_fileio.posix_replace(src, dst)
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) not in _win_fileio.UNSUPPORTED_ERRORS:
                raise
            _posix_replace_supported = False
    os.replace(src, dst)


def _replace(src: Path, dst: Path) -> None:
    """Atomically rename ``src`` over ``dst``, even while ``dst`` is being read.

    On Windows a plain ``os.replace`` fails whenever any other handle has
    ``dst`` open. That never happened while only the CLI touched a run, but the
    API reads manifests and transcripts on other threads while a job rewrites
    them, and a UI polling a run's progress made the run's own manifest
    writes fail at random. See :mod:`meeting_assistant._win_fileio` for the
    POSIX-semantics rename that fixes it; the retry below covers readers that
    did not open the file in a way that allows it.
    """
    delay = _REPLACE_FIRST_DELAY_SEC
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            _replace_once(src, dst)
            return
        except PermissionError:
            if sys.platform != "win32" or attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(delay)
            delay *= 2


def _open_for_read(path: Path):
    """Open an artifact for reading without blocking a concurrent replace."""
    if sys.platform == "win32":
        from meeting_assistant import _win_fileio

        return _win_fileio.open_shared_read(path)
    return open(path, encoding="utf-8")


def write_json(path: str | Path, obj: Any, *, indent: int = 2) -> Path:
    """Serialise ``obj`` to ``path`` atomically, creating parent directories.

    ``ensure_ascii=False`` matters here: transcripts contain Devanagari, and
    escaping it to ``\\uXXXX`` would make every artifact unreadable by eye. Being
    able to open a transcript and see the actual text is worth a lot when
    debugging a code-mixed pipeline.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=indent, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())

    # os.replace is atomic on both POSIX and Windows, and unlike os.rename it
    # overwrites an existing destination on Windows instead of raising.
    _replace(tmp, path)
    return path


def read_json(path: str | Path) -> Any:
    """Load JSON from ``path``, raising :class:`ArtifactError` with the path."""
    path = Path(path)
    if not path.exists():
        raise ArtifactError(f"Artifact not found: {path}")
    try:
        with _open_for_read(path) as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        # Deleted between the exists() check and the open (a --force re-run).
        raise ArtifactError(f"Artifact not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"Artifact is not valid JSON: {path} ({exc})") from exc


def write_text(path: str | Path, text: str) -> Path:
    """Atomically write UTF-8 text, creating parent directories."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    _replace(tmp, path)
    return path


def sha256_file(path: str | Path, *, chunk_size: int = 1 << 20) -> str:
    """Hash a file in chunks.

    Used to fingerprint input audio in the run manifest, so a published result
    can be tied to the exact recording it came from even if the file is later
    renamed or moved. Chunked because audio files are large.
    """
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()
