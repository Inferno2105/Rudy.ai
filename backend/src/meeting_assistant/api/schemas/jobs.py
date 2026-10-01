"""Request and response models for jobs: batch runs, resumes, live sessions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

JobKind = Literal["batch", "resume", "live"]
JobState = Literal["queued", "running", "stopping", "finished", "failed"]


class Job(BaseModel):
    """In-memory state of one job. The run it works on is the durable record;
    this only says whether the server is currently doing something about it."""

    job_id: str
    kind: JobKind
    run_id: str
    state: JobState
    error: str | None = None
    submitted_at: str
    started_at: str | None = None
    finished_at: str | None = None


class JobAccepted(BaseModel):
    job_id: str
    run_id: str


class BatchRequest(BaseModel):
    audio: str = Field(
        description="File name inside the audio directory (see GET /api/audio), never a path"
    )
    num_speakers: int | None = Field(default=None, ge=1, le=20)


class ResumeRequest(BaseModel):
    force_stage: str | None = Field(
        default=None, description="Re-run from this stage, deleting it and every later artifact"
    )
    allow_mixed_config: bool = Field(
        default=False,
        description="Resume even if the configuration changed since the run's earlier stages. "
        "Debugging only: the run is marked inconsistent and excluded from evaluation.",
    )


class LiveStartRequest(BaseModel):
    num_speakers: int | None = Field(default=None, ge=1, le=20)
    device: int | None = Field(default=None, description="Input device index from GET /api/devices")
    use_registry: bool = True
