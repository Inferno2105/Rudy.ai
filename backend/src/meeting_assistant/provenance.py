"""Capture what produced a run, so results stay traceable.

Results from this project are intended for publication, which makes an ordinary
convenience into a requirement: every reported figure has to be attributable to
a specific commit, configuration and set of model versions. A number in a table
that nobody can regenerate is not evidence.

The :func:`config_hash` is the piece that does the real work. Two runs are
comparable only if the settings that affect their output are identical, and
eyeballing a manifest is not a reliable way to establish that. Hashing those
settings turns "is this the same experiment?" into an equality check, which also
means an accidental mid-study change to a model or a prompt shows up as a
different hash rather than quietly contaminating an aggregate.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from meeting_assistant import __version__, config


def _git(*args: str) -> str | None:
    """Run a git command in the repo, returning ``None`` if it fails.

    Provenance capture must never be the reason a run dies, so every failure
    mode here — git missing, not a repository, a detached worktree — degrades to
    ``None`` instead of raising.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=config.REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_state() -> dict[str, Any]:
    """Current commit, branch, and whether the working tree has edits.

    ``dirty`` is recorded rather than prevented. A dirty tree means the commit
    hash alone does not identify the code that ran, which matters when a figure
    is later traced back — better to know the caveat than to have it invisible.
    """
    status = _git("status", "--porcelain")
    return {
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(status) if status is not None else None,
    }


def config_hash(settings: dict[str, str] | None = None) -> str:
    """Stable short hash over the settings that affect output.

    Sorted keys and a canonical separator keep the hash stable across Python
    versions and dict ordering. Twelve hex characters is plenty to distinguish
    the handful of configurations in a study while staying readable in a table.
    """
    settings = settings if settings is not None else config.output_affecting_settings()
    canonical = json.dumps(settings, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def package_versions() -> dict[str, str | None]:
    """Versions of the dependencies whose behaviour affects results.

    pyannote in particular: its 4.x release changed the diarization return type,
    and a future change could alter segmentation behaviour without any change on
    our side. Recording the version is what makes such a shift explainable later
    rather than mysterious.
    """
    from importlib.metadata import PackageNotFoundError, version

    names = ["faster-whisper", "pyannote.audio", "ctranslate2", "torch", "ollama", "numpy"]
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = None
    return versions


def environment() -> dict[str, Any]:
    """Interpreter, platform and dependency versions."""
    return {
        "package_version": __version__,
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "platform_release": platform.release(),
        "packages": package_versions(),
    }


def capture(
    *,
    audio_path: str | Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the provenance block recorded in a run's manifest.

    Args:
        audio_path: input recording. Hashed so a result stays tied to the exact
            audio even if the file is later renamed or moved.
        extra: additional fields to merge in, e.g. prompt versions.
    """
    block: dict[str, Any] = {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "git": git_state(),
        "environment": environment(),
        "settings": config.output_affecting_settings(),
        "config_hash": config_hash(),
    }

    if audio_path is not None:
        from meeting_assistant.io_utils import sha256_file

        path = Path(audio_path)
        block["input"] = {
            "path": str(path),
            "name": path.name,
            "size_bytes": path.stat().st_size if path.exists() else None,
            "sha256": sha256_file(path) if path.exists() else None,
        }

    if extra:
        block.update(extra)
    return block
