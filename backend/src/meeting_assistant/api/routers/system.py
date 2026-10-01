"""Health, input devices, audio files, uploads, the index and the eval report."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from meeting_assistant import __version__, config
from meeting_assistant.api.auth import require_token
from meeting_assistant.api.deps import get_db
from meeting_assistant.api.schemas.system import (
    AudioFile,
    Health,
    IndexRebuildResult,
    InputDevice,
    UploadResult,
)
from meeting_assistant.io_utils import read_json
from meeting_assistant.logging_setup import get_logger
from meeting_assistant.paths import slugify

log = get_logger(__name__)

AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".flac"})
_COPY_CHUNK = 1 << 20

public = APIRouter(tags=["system"])
router = APIRouter(tags=["system"], dependencies=[Depends(require_token)])


@public.get("/health", response_model=Health)
def health() -> Health:
    """Unauthenticated, so a client can tell "server down" from "bad token".
    Deliberately reveals nothing but the version and whether setup is complete."""
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
def list_audio() -> list[AudioFile]:
    if not config.AUDIO_DIR.is_dir():
        return []
    return [
        _describe(path)
        for path in sorted(config.AUDIO_DIR.iterdir())
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    ]


def _sha256(path: Path) -> str:
    from meeting_assistant.io_utils import sha256_file

    return sha256_file(path)


@router.post("/uploads", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
def upload_audio(request: Request, file: UploadFile = File(...)) -> UploadResult:
    """Store an audio file in the audio directory under a sanitized name.

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

    config.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    partial = config.AUDIO_DIR / f".upload-{uuid.uuid4().hex}.part"
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
        target = config.AUDIO_DIR / name
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
    """Re-ingest every run directory -- the API form of ``meeting-assistant reindex``."""
    from meeting_assistant.paths import list_runs
    from meeting_assistant.store.ingest import reindex_all

    runs = list_runs()
    return IndexRebuildResult(indexed=reindex_all(conn, runs), total=len(runs))


@router.get("/eval/report")
def eval_report() -> dict[str, Any]:
    """The latest ``meeting-assistant eval`` report, as written to disk."""
    path = config.EVAL_DIR / "reports" / "latest.json"
    if not path.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No evaluation report yet; run `meeting-assistant eval`"
        )
    return read_json(path)
