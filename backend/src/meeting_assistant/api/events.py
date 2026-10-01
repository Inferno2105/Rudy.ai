"""Server-sent events: live progress for one run.

Progress is derived entirely from what the pipeline already writes to disk --
the manifest after every stage, and ``05_tagged.json`` after every live chunk
-- rather than from callbacks threaded through the pipeline. That keeps the
pipeline ignorant of the API, and means a client that connects late, or
reconnects after a dropped connection, sees exactly the same state as one
that was watching from the start: the files are the state.

Events:

``manifest`` -- ``{status, stages, extra}`` whenever the manifest changes.
``segments`` -- ``{start_index, segments}`` for transcript segments appended
since the last event (live runs grow their transcript chunk by chunk).
``job`` -- the in-memory job state, whenever it changes.
``end`` -- sent once the run has no active job; the stream then closes.

A ``: keepalive`` comment goes out every 15 seconds of silence so proxies and
browsers don't drop an idle connection mid-meeting.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Request

from meeting_assistant.api.jobs import JobManager
from meeting_assistant.errors import ArtifactError
from meeting_assistant.io_utils import read_json
from meeting_assistant.paths import RunPaths

POLL_INTERVAL_SEC = 1.0
KEEPALIVE_SEC = 15.0


def _format(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _read(path: Path) -> Any | None:
    """Read JSON, or ``None`` if it is missing or mid-replace.

    Writes are atomic renames, but on Windows opening a file at the instant
    ``os.replace`` swaps it can still raise a sharing violation -- skipping one
    poll is the right response, not an error.
    """
    try:
        return read_json(path)
    except (ArtifactError, OSError):
        return None


async def run_events(
    paths: RunPaths,
    jobs: JobManager,
    request: Request,
    *,
    poll_interval: float | None = None,
) -> AsyncIterator[str]:
    poll_interval = poll_interval if poll_interval is not None else POLL_INTERVAL_SEC
    manifest_mtime: float | None = None
    tagged_mtime: float | None = None
    segments_sent = 0
    last_job: dict[str, Any] | None = None
    last_sent = time.monotonic()
    tagged_path = paths.artifact("tagged")

    while True:
        if await request.is_disconnected():
            return

        # Sampled before reading the files, not after: if the job was already
        # inactive here, every write it made precedes the reads below, so the
        # final pass cannot miss the last manifest update.
        active = jobs.is_active(paths.run_id)
        out: list[str] = []

        mtime = _mtime(paths.manifest_path)
        if mtime is not None and mtime != manifest_mtime:
            manifest = await asyncio.to_thread(_read, paths.manifest_path)
            if manifest is not None:
                manifest_mtime = mtime
                out.append(
                    _format(
                        "manifest",
                        {
                            "status": manifest.get("status"),
                            "stages": manifest.get("stages", []),
                            "extra": manifest.get("extra", {}),
                        },
                    )
                )

        mtime = _mtime(tagged_path)
        if mtime is not None and mtime != tagged_mtime:
            segments = await asyncio.to_thread(_read, tagged_path)
            if isinstance(segments, list):
                tagged_mtime = mtime
                if len(segments) > segments_sent:
                    out.append(
                        _format(
                            "segments",
                            {"start_index": segments_sent, "segments": segments[segments_sent:]},
                        )
                    )
                    segments_sent = len(segments)

        job = jobs.latest_for_run(paths.run_id)
        job_dict = job.model_dump() if job else None
        if job_dict != last_job:
            last_job = job_dict
            if job_dict is not None:
                out.append(_format("job", job_dict))

        for chunk in out:
            yield chunk
        if out:
            last_sent = time.monotonic()
        elif time.monotonic() - last_sent >= KEEPALIVE_SEC:
            yield ": keepalive\n\n"
            last_sent = time.monotonic()

        if not active:
            yield _format("end", {"run_id": paths.run_id})
            return

        await asyncio.sleep(poll_interval)
