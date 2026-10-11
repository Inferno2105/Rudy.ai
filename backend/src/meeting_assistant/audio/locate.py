"""Find a run's recording on this machine, even if it was made on another.

A manifest records the recording's path as the machine that ran the pipeline
saw it: ``C:\\Users\\...\\data\\audio\\test.wav`` natively on Windows,
``/app/data/audio/users/<uid>/x.wav`` in Docker. Both point into the same
``data/audio`` folder (Docker bind-mounts it), so a path that does not exist
here is looked up by its location *within* the audio folder instead.

A relocated file is accepted only if its sha256 equals the one the manifest
recorded: the same name with different bytes is a different recording, and
playing or reprocessing it would silently break the run's provenance.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from meeting_assistant import config
from meeting_assistant.io_utils import sha256_file

_AUDIO_FOLDER = "audio"


@lru_cache(maxsize=256)
def _sha256(path: str, mtime_ns: int, size: int) -> str:  # noqa: ARG001 -- mtime and size are the cache key
    return sha256_file(path)


def _within_audio_folder(recorded: str) -> list[str] | None:
    """The parts of ``recorded`` after its last ``audio`` folder, either separator style."""
    parts = [part for part in re.split(r"[\\/]+", recorded) if part]
    for index in range(len(parts) - 2, -1, -1):
        if parts[index].lower() == _AUDIO_FOLDER:
            return parts[index + 1 :]
    return None


def locate_recording(recorded: str | None, sha256: str | None) -> Path | None:
    """The recording a manifest names, as a file inside this machine's audio folder.

    Returns ``None`` if it is not there, lies outside the audio folder, or (when
    relocated) its contents differ from what the manifest recorded.
    """
    if not recorded:
        return None
    audio_dir = config.AUDIO_DIR.resolve()

    direct = Path(recorded)
    if not direct.is_absolute():
        direct = config.REPO_ROOT / direct
    try:
        direct = direct.resolve()
        if direct.is_relative_to(audio_dir) and direct.is_file():
            return direct
    except OSError:
        pass  # e.g. a Windows drive path on Linux; try relocating instead

    tail = _within_audio_folder(recorded)
    if not tail or any(part in (".", "..") for part in tail):
        return None
    candidate = audio_dir.joinpath(*tail).resolve()
    if not candidate.is_relative_to(audio_dir) or not candidate.is_file():
        return None
    if sha256:
        stat = candidate.stat()
        if _sha256(str(candidate), stat.st_mtime_ns, stat.st_size) != sha256:
            return None
    return candidate
