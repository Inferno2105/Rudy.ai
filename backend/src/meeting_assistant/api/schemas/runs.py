"""Response models for runs and the artifacts a run produces.

These mirror the artifact shapes the pipeline already writes (see
``pipeline/stages.py`` and the modules each stage calls) rather than defining
new ones: the API reads artifacts off disk and validates them into these
models, so the OpenAPI schema -- and the TypeScript client generated from it
-- describes exactly what is on disk.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from meeting_assistant.api.schemas.jobs import Job


class RunSummary(BaseModel):
    """One row of the run list, from the SQLite index."""

    run_id: str
    mode: str
    status: str
    data_origin: str
    created_at: str | None = None
    finished_at: str | None = None
    git_commit: str | None = None
    config_hash: str | None = None
    audio_path: str | None = None


class StageInfo(BaseModel):
    name: str
    status: str
    seconds: float = 0.0
    counts: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class RunDetail(BaseModel):
    """One run, read from its manifest on disk (the source of truth)."""

    run_id: str
    mode: str
    status: str
    data_origin: str
    provenance: dict[str, Any]
    stages: list[StageInfo]
    extra: dict[str, Any]
    artifacts: list[str] = Field(description="Artifact names present on disk, in pipeline order")
    job: Job | None = Field(default=None, description="The in-memory job for this run, if any")


class Segment(BaseModel):
    """A transcript segment. Fields beyond the core five depend on which
    stages ran (e.g. live runs add ``chunk`` and speaker-resolution fields)."""

    model_config = ConfigDict(extra="allow")

    start: float
    end: float
    speaker: str | None = None
    text: str = ""
    language: str | None = None
    speaker_overlap: float | None = None
    speaker_resolution: str | None = None
    local_speaker: str | None = None
    speaker_confidence: float | None = None
    chunk: int | None = None


class TranscriptResponse(BaseModel):
    source_artifact: str = Field(
        description="Which artifact these segments came from -- hinglish, tagged, merged or "
        "aligned, the first one present"
    )
    segments: list[Segment]


class SummaryResponse(BaseModel):
    summary: str = ""
    highlights: list[str] = Field(default_factory=list)
    key_decisions: list[str] = Field(default_factory=list)


class ActionItem(BaseModel):
    person: str | None = None
    task: str = ""
    deadline: str | None = None
    status: str | None = None


class ActionItemsResponse(BaseModel):
    action_items: list[ActionItem]


class SpeakerStat(BaseModel):
    speaking_time_sec: float
    participation_pct: float
    utterance_count: int
    word_count: int
    words_per_minute: float = 0.0
    mean_utterance_sec: float = 0.0


class SpeakerTotals(BaseModel):
    model_config = ConfigDict(extra="allow")

    num_speakers: int
    attributed_time_sec: float = 0.0
    unattributed_time_sec: float = 0.0
    unattributed_pct: float = 0.0
    total_speaking_time_sec: float = 0.0
    utterance_count: int = 0
    word_count: int = 0


class SpeakersResponse(BaseModel):
    speakers: dict[str, SpeakerStat]
    totals: SpeakerTotals


class MetadataResponse(BaseModel):
    meeting_id: str
    date: str
    time: str
    duration_sec: float
    duration_readable: str
    num_speakers: int
    languages_used: list[str]
    total_word_count: int
    segment_count: int
