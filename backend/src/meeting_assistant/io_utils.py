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
from pathlib import Path
from typing import Any

from meeting_assistant.errors import ArtifactError


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
    os.replace(tmp, path)
    return path


def read_json(path: str | Path) -> Any:
    """Load JSON from ``path``, raising :class:`ArtifactError` with the path."""
    path = Path(path)
    if not path.exists():
        raise ArtifactError(f"Artifact not found: {path}")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"Artifact is not valid JSON: {path} ({exc})") from exc


def write_text(path: str | Path, text: str) -> Path:
    """Atomically write UTF-8 text, creating parent directories."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
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
