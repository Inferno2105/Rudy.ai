"""Jobs and live recording control."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from meeting_assistant.api.auth import require_token
from meeting_assistant.api.deps import get_jobs
from meeting_assistant.api.jobs import BusyError, JobManager, NoLiveJobError
from meeting_assistant.api.schemas.jobs import Job, JobAccepted, LiveStartRequest

router = APIRouter(tags=["jobs"], dependencies=[Depends(require_token)])


@router.get("/jobs", response_model=list[Job])
def list_jobs(jobs: JobManager = Depends(get_jobs)) -> list[Job]:
    """Recent jobs, newest first (in memory only; cleared on restart)."""
    return jobs.list_jobs()


@router.get("/jobs/current", response_model=Job | None)
def current_job(jobs: JobManager = Depends(get_jobs)) -> Job | None:
    return jobs.current()


@router.post("/live/start", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
def start_live(body: LiveStartRequest, jobs: JobManager = Depends(get_jobs)) -> JobAccepted:
    """Start recording from the server's microphone. 409 if a job is busy."""
    from meeting_assistant.pipeline.live import LiveOptions

    opts = LiveOptions(
        num_speakers=body.num_speakers, device=body.device, use_registry=body.use_registry
    )
    try:
        job = jobs.start_live(opts)
    except BusyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return JobAccepted(job_id=job.job_id, run_id=job.run_id)


@router.post("/live/stop", response_model=Job, status_code=status.HTTP_202_ACCEPTED)
def stop_live(jobs: JobManager = Depends(get_jobs)) -> Job:
    """Stop recording. The job then drains queued chunks and runs the
    summary stages, so it stays ``stopping`` for a while before finishing."""
    try:
        return jobs.stop_live()
    except NoLiveJobError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
