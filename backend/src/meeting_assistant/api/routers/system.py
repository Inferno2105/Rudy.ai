"""Health, input devices, audio files, uploads, the index and the eval report."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from meeting_assistant import __version__, accounts, config
from meeting_assistant.api.auth import require_user
from meeting_assistant.api.deps import get_audio_file, get_db, get_jobs
from meeting_assistant.api.jobs import JobManager
from meeting_assistant.api.schemas.eval import EvalReport
from meeting_assistant.api.schemas.system import (
    AudioFile,
    Health,
    IndexRebuildResult,
    InputDevice,
    UploadResult,
)
from meeting_assistant.io_utils import read_json
from meeting_assistant.logging_setup import get_logger
from meeting_assistant.ownership import claim_if_single_user, user_audio_dir
from meeting_assistant.paths import slugify

log = get_logger(__name__)

AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".flac"})
_COPY_CHUNK = 1 << 20

# Health is public, so the sign-in page can tell "server down" from
# "not signed in". Everything else needs a signed-in user.
public = APIRouter(tags=["system"])
router = APIRouter(tags=["system"], dependencies=[Depends(require_user)])


@public.get("/health", response_model=Health)
def health() -> Health:
    """The version, and whether setup is complete (with what is missing)."""
    problems = config.list_problems(require_hf_token=True, require_ffmpeg=True)
    return Health(version=__version__, ok=not problems, problems=problems)


@router.get("/devices", response_model=list[InputDevice])
def devices() -> list[InputDevice]:
    """Microphone inputs on the server, for choosing a live-recording device."""
    try:
        import sounddevice as sd

        found = sd.query_devices()
        default_input = sd.default.device[0]
    except Exception as exc:  # noqa: BLE001 -- PortAudio missing or no audio subsystem
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Audio devices unavailable: {exc}"
        ) from exc

    return [
        InputDevice(
            index=index,
            name=device["name"],
            channels=device["max_input_channels"],
            default_samplerate=device["default_samplerate"],
            is_default=index == default_input,
        )
        for index, device in enumerate(found)
        if device["max_input_channels"] > 0
    ]


def _describe(path: Path) -> AudioFile:
    duration = None
    if path.suffix.lower() == ".wav":
        from meeting_assistant.audio.wav_io import probe_wav

        try:
            duration = probe_wav(path)["duration_sec"]
        except Exception:  # noqa: BLE001 -- a malformed WAV still gets listed, just without a duration
            duration = None
    return AudioFile(name=path.name, size_bytes=path.stat().st_size, duration_sec=duration)


@router.get("/audio", response_model=list[AudioFile])
def list_audio(
    user: accounts.User = Depends(require_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[AudioFile]:
    """Recordings you have uploaded (never another account's)."""
    from meeting_assistant.store.queries import count_runs_from_upload

    folder = user_audio_dir(user.uid)
    if not folder.is_dir():
        return []
    files = []
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
            described = _describe(path)
            described.meetings = count_runs_from_upload(conn, owner=user.uid, name=path.name)
            files.append(described)
    return files


def _being_processed(path: Path, jobs: JobManager, user: accounts.User) -> bool:
    """Whether one of the user's queued or running jobs reads this recording."""
    from meeting_assistant.audio.locate import locate_recording
    from meeting_assistant.paths import RunPaths

    target = path.resolve()
    for job in jobs.list_jobs(owner=user.uid):
        if job.state not in ("queued", "running", "stopping"):
            continue
        manifest_path = RunPaths(run_id=job.run_id, root=config.RUNS_DIR / job.run_id).manifest_path
        if not manifest_path.is_file():
            continue
        recorded = (read_json(manifest_path).get("provenance") or {}).get("input") or {}
        if locate_recording(recorded.get("path"), recorded.get("sha256")) == target:
            return True
    return False


@router.delete(
    "/audio/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"description": "No such recording among yours"},
        409: {"description": "A queued or running job is processing it"},
    },
)
def delete_audio(
    name: str,
    jobs: JobManager = Depends(get_jobs),
    user: accounts.User = Depends(require_user),
) -> None:
    """Delete one of your uploaded recordings.

    Meetings already made from it keep their transcripts, summaries and
    provenance (including the recording's sha256); only playback stops working.
    """
    path = get_audio_file(name, user)
    if _being_processed(path, jobs, user):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A meeting is being processed from this recording. Delete it when that finishes.",
        )
    path.unlink()
    log.info("Deleted upload %s of account %s", name, user.uid)


def _sha256(path: Path) -> str:
    from meeting_assistant.io_utils import sha256_file

    return sha256_file(path)


@router.post("/uploads", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
def upload_audio(
    request: Request,
    file: UploadFile = File(...),
    user: accounts.User = Depends(require_user),
) -> UploadResult:
    """Store an audio file in your own upload folder under a sanitized name.

    The name is reduced to a safe slug (so a client cannot choose where the
    file lands), and an existing file of the same name is never overwritten
    with different content: runs record their input's sha256 for provenance,
    and silently replacing the bytes behind a name would break that link for
    every earlier run of it.
    """
    max_bytes = config.API_MAX_UPLOAD_MB * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes + 1024 * 1024:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Upload exceeds the size limit")

    original = Path(file.filename or "")
    suffix = original.suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Unsupported audio type {suffix or '(none)'}; expected one of "
            f"{', '.join(sorted(AUDIO_EXTENSIONS))}",
        )
    name = f"{slugify(original.stem)}{suffix}"

    folder = user_audio_dir(user.uid)
    folder.mkdir(parents=True, exist_ok=True)
    partial = folder / f".upload-{uuid.uuid4().hex}.part"
    digest = hashlib.sha256()
    size = 0
    try:
        with open(partial, "wb") as out:
            while block := file.file.read(_COPY_CHUNK):
                size += len(block)
                if size > max_bytes:
                    raise HTTPException(
                        status.HTTP_413_CONTENT_TOO_LARGE,
                        f"Upload exceeds the {config.API_MAX_UPLOAD_MB} MB limit",
                    )
                digest.update(block)
                out.write(block)

        sha256 = digest.hexdigest()
        target = folder / name
        if target.exists():
            if _sha256(target) != sha256:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"A different file named {name} already exists; rename and re-upload",
                )
            partial.unlink()
            already_present = True
        else:
            os.replace(partial, target)
            log.info("Stored upload %s (%d bytes)", name, size)
            already_present = False
        return UploadResult(
            **_describe(target).model_dump(), sha256=sha256, already_present=already_present
        )
    finally:
        if partial.exists():
            partial.unlink()


@router.post("/index/rebuild", response_model=IndexRebuildResult)
def rebuild_index(conn: sqlite3.Connection = Depends(get_db)) -> IndexRebuildResult:
    """Re-ingest every run directory -- the API form of ``meeting-assistant reindex``.

    With a single account, runs the CLI made without ``--user`` become that
    account's first (see :mod:`meeting_assistant.ownership`).
    """
    from meeting_assistant.paths import list_runs
    from meeting_assistant.store.ingest import reindex_all

    claim_if_single_user()
    runs = list_runs()
    return IndexRebuildResult(indexed=reindex_all(conn, runs), total=len(runs))


@router.get("/eval/report", response_model=EvalReport)
def eval_report() -> dict[str, Any]:
    """The latest ``meeting-assistant eval`` report, as written to disk."""
    path = config.EVAL_DIR / "reports" / "latest.json"
    if not path.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No evaluation report yet; run `meeting-assistant eval`"
        )
    return read_json(path)
