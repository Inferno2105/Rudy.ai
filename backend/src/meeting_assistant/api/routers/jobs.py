"""Jobs and live recording control."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from meeting_assistant import accounts
from meeting_assistant.api.auth import require_user
from meeting_assistant.api.deps import get_jobs
from meeting_assistant.api.jobs import BusyError, JobManager, NoLiveJobError
from meeting_assistant.api.schemas.jobs import Job, JobAccepted, LiveStartRequest

router = APIRouter(tags=["jobs"], dependencies=[Depends(require_user)])


@router.get("/jobs", response_model=list[Job])
def list_jobs(
    jobs: JobManager = Depends(get_jobs), user: accounts.User = Depends(require_user)
) -> list[Job]:
    """Your recent jobs, newest first (in memory only; cleared on restart)."""
    return jobs.list_jobs(owner=user.uid)


@router.get("/jobs/current", response_model=Job | None)
def current_job(
    jobs: JobManager = Depends(get_jobs), user: accounts.User = Depends(require_user)
) -> Job | None:
    """The running job, if it is yours."""
    return jobs.current(owner=user.uid)


@router.post("/live/start", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
def start_live(
    body: LiveStartRequest,
    jobs: JobManager = Depends(get_jobs),
    user: accounts.User = Depends(require_user),
) -> JobAccepted:
    """Prepare a live session: load the models and open the server's
    microphone. Recording begins with ``POST /api/live/record``; the session's
    progress is in its run's ``extra.live_phase`` (``loading``, ``ready``,
    ``recording``, ``finishing``). 409 if a job is busy."""
    from meeting_assistant.pipeline.live import LiveOptions

    opts = LiveOptions(
        num_speakers=body.num_speakers, device=body.device, use_registry=body.use_registry
    )
    try:
        job = jobs.start_live(opts, owner=user.uid)
    except BusyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return JobAccepted(job_id=job.job_id, run_id=job.run_id)


@router.post("/live/stop", response_model=Job, status_code=status.HTTP_202_ACCEPTED)
def stop_live(
    jobs: JobManager = Depends(get_jobs), user: accounts.User = Depends(require_user)
) -> Job:
    """Stop recording. The job then drains queued chunks and runs the
    summary stages, so it stays ``stopping`` for a while before finishing."""
    try:
        return jobs.stop_live(owner=user.uid)
    except NoLiveJobError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/live/record", response_model=Job, status_code=status.HTTP_202_ACCEPTED)
def begin_recording(
    jobs: JobManager = Depends(get_jobs), user: accounts.User = Depends(require_user)
) -> Job:
    """Start recording in your prepared live session. If it is still getting
    ready, it starts recording the moment it is."""
    try:
        return jobs.begin_recording(owner=user.uid)
    except NoLiveJobError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


LEVEL_INTERVAL_SEC = 0.08


@router.get(
    "/live/level",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "``text/event-stream`` of ``level`` events (LevelEvent) while your "
            "live session is active",
            "content": {
                "text/event-stream": {"schema": {"$ref": "#/components/schemas/LevelEvent"}}
            },
        },
        404: {"description": "You have no live session"},
    },
)
async def stream_level(
    request: Request,
    jobs: JobManager = Depends(get_jobs),
    user: accounts.User = Depends(require_user),
) -> StreamingResponse:
    """The microphone's loudness, about twelve times a second, for a level
    meter: from the moment the microphone opens until the session ends."""
    if jobs.live_level_meter(owner=user.uid) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You have no live session")

    async def events():
        while not await request.is_disconnected():
            meter = jobs.live_level_meter(owner=user.uid)
            if meter is None:
                return
            payload = json.dumps({"level": round(meter.read(), 3)})
            yield f"event: level\ndata: {payload}\n\n"
            await asyncio.sleep(LEVEL_INTERVAL_SEC)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
