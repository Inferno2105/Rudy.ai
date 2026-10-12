"""Response models for runs and the artifacts a run produces.

These mirror the artifact shapes the pipeline already writes (see
``pipeline/stages.py`` and the modules each stage calls) rather than defining
new ones: the API reads artifacts off disk and validates them into these
models, so the OpenAPI schema -- and the TypeScript client generated from it
-- describes exactly what is on disk.
"""

from __future__ import annotations

from typing import Any, Literal

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
    speakers: list[str] = Field(
        default_factory=list, description="Speaker labels, most speaking time first"
    )
    duration_sec: float | None = Field(default=None, description="End of the last segment")
    language_mix: dict[str, float] = Field(
        default_factory=dict, description="Share of speech time per language tag (sums to 1)"
    )


class StageInfo(BaseModel):
    name: str
    status: str
    seconds: float = 0.0
    counts: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    execution: int = Field(default=0, description="Which execution produced this stage")


class Consistency(BaseModel):
    """Whether the stages on disk share one configuration and one clean commit."""

    executions: list[int] = Field(description="Executions that produced the recorded stages")
    config: bool
    code: bool


class RunDetail(BaseModel):
    """One run, read from its manifest on disk (the source of truth)."""

    run_id: str
    mode: str
    status: str
    data_origin: str
    provenance: dict[str, Any] = Field(description="Provenance of execution 0 (the run itself)")
    resumes: list[dict[str, Any]] = Field(
        default_factory=list, description="Provenance of each later execution (1, 2, ...)"
    )
    consistency: Consistency
    evaluation_ineligibility: str | None = Field(
        default=None,
        description="Why this run must not feed a reported number; null if it may",
    )
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


class TranslationStatus(BaseModel):
    """A full translation of the transcript, or how far making one has got.

    ``missing`` means none exists for the current transcript (never made, or
    made before the transcript was re-generated); ``POST`` the same path to
    make one. ``segments`` is present only when ``ready``.
    """

    target: Literal["english", "hindi"]
    state: Literal["missing", "queued", "running", "ready", "failed"]
    done: int | None = Field(default=None, description="Segments translated so far")
    total: int | None = None
    error: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    created_at: str | None = None
    segments_failed: int = Field(
        default=0, description="Segments the model could not translate; shown as spoken"
    )
    segments: list[Segment] | None = None


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


class WaveformResponse(BaseModel):
    """The recording's loudness envelope, for drawing its waveform."""

    duration_sec: float = Field(description="Length of the recording")
    peaks: list[float] = Field(description="RMS loudness per equal time slice, 0..1")


class SearchHit(BaseModel):
    """One transcript line that matches a search, from the index."""

    run_id: str
    idx: int = Field(description="Position of the segment in the run's transcript")
    start: float | None = None
    end: float | None = None
    speaker: str | None = None
    language: str | None = None
    text: str
    mode: str
    created_at: str | None = None
    audio_path: str | None = None
