"""Jobs and live recording control."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

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
    """Start recording from the server's microphone. 409 if a job is busy."""
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
