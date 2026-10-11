"""Shared request dependencies: safe path resolution and database access.

Every path the API touches is built from a client-supplied string (a run id,
an audio file name), so each one is validated and then checked to resolve
*inside* the directory it is meant to be in. Character validation alone is
not enough on Windows, where a drive-relative or UNC form can still escape;
the resolve-and-compare step is what actually guarantees it.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from fastapi import HTTPException, Request, status

from meeting_assistant import config
from meeting_assistant.api.jobs import JobManager
from meeting_assistant.paths import RunPaths
from meeting_assistant.store.db import open_db

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def safe_child(base: Path, name: str) -> Path:
    """``base / name``, or a 400 if ``name`` could point anywhere else."""
    if not _SAFE_NAME_RE.fullmatch(name) or ".." in name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid name: {name!r}")
    base_resolved = base.resolve()
    candidate = (base_resolved / name).resolve()
    if candidate.parent != base_resolved:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid name: {name!r}")
    return candidate


def get_run_paths(run_id: str) -> RunPaths:
    """Path dependency for ``/runs/{run_id}/...`` routes."""
    root = safe_child(config.RUNS_DIR, run_id)
    if not root.is_dir():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No such run: {run_id}")
    return RunPaths(run_id=run_id, root=root)


def get_audio_file(name: str) -> Path:
    """An existing file inside ``AUDIO_DIR``, by bare file name."""
    path = safe_child(config.AUDIO_DIR, name)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No such audio file: {name}")
    return path


def get_jobs(request: Request) -> JobManager:
    return request.app.state.jobs


def get_db() -> Iterator[sqlite3.Connection]:
    """One connection per request, never shared between requests.

    FastAPI may run this dependency's setup and teardown on different pool
    threads, so the connection is opened with ``cross_thread``: without it,
    closing it after the response raised sqlite3.ProgrammingError in the
    server log.
    """
    with open_db(config.INDEX_DB_PATH, cross_thread=True) as conn:
        yield conn
