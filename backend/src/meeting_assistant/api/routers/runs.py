"""Runs: list, inspect, read artifacts, start, resume, and watch progress."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse

from meeting_assistant import accounts, config
from meeting_assistant.api.auth import require_user
from meeting_assistant.api.deps import get_audio_file, get_db, get_jobs, get_run_paths
from meeting_assistant.api.events import run_events
from meeting_assistant.api.jobs import BusyError, JobManager
from meeting_assistant.api.schemas.jobs import BatchRequest, JobAccepted, ResumeRequest
from meeting_assistant.api.schemas.runs import (
    ActionItemsResponse,
    MetadataResponse,
    RunDetail,
    RunSummary,
    SearchHit,
    SpeakersResponse,
    SummaryResponse,
    TranscriptResponse,
    WaveformResponse,
)
from meeting_assistant.errors import ArtifactError, ProvenanceError
from meeting_assistant.io_utils import read_json
from meeting_assistant.paths import ARTIFACTS, RunPaths
from meeting_assistant.store import queries

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(require_user)])

ArtifactName = Literal[tuple(ARTIFACTS)]  # type: ignore[valid-type]


def _manifest(paths: RunPaths) -> dict[str, Any]:
    if not paths.manifest_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {paths.run_id} has no manifest yet")
    return read_json(paths.manifest_path)


def _artifact(paths: RunPaths, name: str) -> Any:
    if not paths.has(name):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Run {paths.run_id} has no {name} artifact (yet)"
        )
    return read_json(paths.artifact(name))


@router.get("", response_model=list[RunSummary])
def list_runs(
    status_filter: str | None = Query(default=None, alias="status"),
    mode: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
    user: accounts.User = Depends(require_user),
) -> list[dict[str, Any]]:
    """Your runs from the SQLite index, newest first. Re-indexed automatically
    when a job finishes; ``POST /api/index/rebuild`` covers runs made by the CLI."""
    return queries.list_runs(
        conn, limit=limit, offset=offset, status=status_filter, mode=mode, owner=user.uid
    )


@router.get("/search", response_model=list[SearchHit])
def search(
    q: str = Query(min_length=1, max_length=200, description="Text to find"),
    limit: int = Query(default=20, ge=1, le=100),
    conn: sqlite3.Connection = Depends(get_db),
    user: accounts.User = Depends(require_user),
) -> list[dict[str, Any]]:
    """Transcript lines across all your meetings that contain ``q``."""
    return queries.search_segments(conn, q, owner=user.uid, limit=limit)


@router.post("/batch", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
def start_batch(
    body: BatchRequest,
    jobs: JobManager = Depends(get_jobs),
    user: accounts.User = Depends(require_user),
) -> JobAccepted:
    """Process one of your uploaded recordings."""
    audio_path = get_audio_file(body.audio, user)
    try:
        job = jobs.submit_batch(audio_path, body, owner=user.uid)
    except ArtifactError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return JobAccepted(job_id=job.job_id, run_id=job.run_id)


@router.get("/{run_id}", response_model=RunDetail)
def get_run(
    paths: RunPaths = Depends(get_run_paths), jobs: JobManager = Depends(get_jobs)
) -> RunDetail:
    """One run, read from disk -- the manifest is authoritative, not the index."""
    manifest = _manifest(paths)
    from meeting_assistant.pipeline.manifest import RunManifest

    loaded = RunManifest.load(paths)
    return RunDetail(
        run_id=paths.run_id,
        mode=manifest.get("mode", ""),
        status=manifest.get("status", ""),
        data_origin=manifest.get("data_origin", ""),
        provenance=manifest.get("provenance", {}),
        resumes=manifest.get("resumes", []),
        # Recomputed rather than read, so manifests written before executions
        # were tracked still report it.
        consistency=loaded.consistency(),
        evaluation_ineligibility=loaded.evaluation_ineligibility(),
        stages=manifest.get("stages", []),
        extra=manifest.get("extra", {}),
        artifacts=paths.existing_artifacts(),
        job=jobs.latest_for_run(paths.run_id),
    )


@router.post("/{run_id}/resume", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
def resume_run(
    body: ResumeRequest,
    paths: RunPaths = Depends(get_run_paths),
    jobs: JobManager = Depends(get_jobs),
    user: accounts.User = Depends(require_user),
) -> JobAccepted:
    """Run whatever stages have not completed, or re-run from ``force_stage``.

    Refused with 409 if it would mix configurations or recordings in one run;
    checked here, before queueing, so the refusal reaches the caller instead of
    surfacing later as a failed job.
    """
    from meeting_assistant.pipeline.manifest import RunManifest
    from meeting_assistant.pipeline.stages import STAGES_BY_NAME

    manifest = _manifest(paths)
    if manifest.get("mode") != "batch":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only batch runs can be resumed")
    if body.force_stage is not None and body.force_stage not in STAGES_BY_NAME:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Unknown stage {body.force_stage!r}; known: {', '.join(STAGES_BY_NAME)}",
        )
    try:
        RunManifest.load(paths).check_resumable(
            force_stage=body.force_stage, allow_mixed_config=body.allow_mixed_config
        )
    except ProvenanceError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    try:
        job = jobs.submit_resume(
            paths,
            force_stage=body.force_stage,
            allow_mixed_config=body.allow_mixed_config,
            owner=user.uid,
        )
    except BusyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return JobAccepted(job_id=job.job_id, run_id=job.run_id)


@router.get("/{run_id}/transcript", response_model=TranscriptResponse)
def get_transcript(paths: RunPaths = Depends(get_run_paths)) -> TranscriptResponse:
    """The most processed transcript available (hinglish, else tagged, merged,
    aligned) -- the same choice the summary and statistics stages make."""
    from meeting_assistant.pipeline.stages import resolve_intel_input

    try:
        source, segments = resolve_intel_input(paths)
    except ArtifactError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return TranscriptResponse(source_artifact=source, segments=segments)


@router.get("/{run_id}/summary", response_model=SummaryResponse)
def get_summary(paths: RunPaths = Depends(get_run_paths)) -> Any:
    return _artifact(paths, "summary")


@router.get("/{run_id}/action-items", response_model=ActionItemsResponse)
def get_action_items(paths: RunPaths = Depends(get_run_paths)) -> Any:
    return _artifact(paths, "action_items")


@router.get("/{run_id}/speakers", response_model=SpeakersResponse)
def get_speakers(paths: RunPaths = Depends(get_run_paths)) -> Any:
    return _artifact(paths, "speaker_stats")


@router.get("/{run_id}/metadata", response_model=MetadataResponse)
def get_metadata(paths: RunPaths = Depends(get_run_paths)) -> Any:
    return _artifact(paths, "metadata")


@router.get("/{run_id}/artifacts/{name}")
def get_raw_artifact(name: ArtifactName, paths: RunPaths = Depends(get_run_paths)) -> Any:
    """Any artifact, exactly as written -- for debugging and supplementary material."""
    return _artifact(paths, name)


def _source_audio(paths: RunPaths) -> Path:
    """The run's recording, only if it resolves inside the audio directory.

    The path comes from a manifest on disk, and serving it must never become a
    way to read arbitrary files that happen to be named there.
    """
    recorded = ((_manifest(paths).get("provenance") or {}).get("input") or {}).get("path")
    if not recorded:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This run has no single source recording")

    audio_dir = config.AUDIO_DIR.resolve()
    candidate = Path(recorded)
    if not candidate.is_absolute():
        candidate = config.REPO_ROOT / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(audio_dir) or not candidate.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source recording is not available")
    return candidate


@router.get("/{run_id}/audio", response_class=FileResponse)
def get_run_audio(paths: RunPaths = Depends(get_run_paths)) -> FileResponse:
    """The run's source recording, for playback alongside its transcript.

    Supports HTTP Range requests, so the player can seek.
    """
    return FileResponse(_source_audio(paths))


@router.get("/{run_id}/waveform", response_model=WaveformResponse)
def get_run_waveform(
    bins: int = Query(default=600, ge=32, le=2000),
    paths: RunPaths = Depends(get_run_paths),
) -> WaveformResponse:
    """The recording's loudness envelope in ``bins`` equal slices, for the
    player's waveform -- a few kilobytes instead of the whole recording."""
    from meeting_assistant.audio.waveform import waveform

    source = _source_audio(paths)
    try:
        duration, peaks = waveform(source, bins)
    except Exception as exc:  # noqa: BLE001 -- an undecodable file has no waveform, not a 500
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Could not read the recording: {exc}"
        ) from exc
    return WaveformResponse(duration_sec=duration, peaks=peaks)


@router.get(
    "/{run_id}/events",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "``text/event-stream`` of ``manifest`` (ManifestEvent), "
            "``segments`` (SegmentsEvent), ``job`` (Job) and finally ``end`` (EndEvent)",
            "content": {
                "text/event-stream": {
                    "schema": {
                        "oneOf": [
                            {"$ref": "#/components/schemas/ManifestEvent"},
                            {"$ref": "#/components/schemas/SegmentsEvent"},
                            {"$ref": "#/components/schemas/Job"},
                            {"$ref": "#/components/schemas/EndEvent"},
                        ]
                    }
                }
            },
        }
    },
)
async def stream_events(
    request: Request,
    paths: RunPaths = Depends(get_run_paths),
    jobs: JobManager = Depends(get_jobs),
) -> StreamingResponse:
    """Server-sent progress events; see ``meeting_assistant.api.events``."""
    return StreamingResponse(
        run_events(paths, jobs, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
