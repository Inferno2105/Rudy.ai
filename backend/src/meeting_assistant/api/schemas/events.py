"""Payloads of the server-sent events on ``GET /api/runs/{run_id}/events``.

An SSE stream is plain text, so FastAPI cannot infer these from the route's
return type. They are declared here and added to the OpenAPI components (see
``meeting_assistant.api.app``) so the frontend's event handling is typed from
the same generated schema as every other response, instead of from a
hand-written copy that could drift. :mod:`meeting_assistant.api.events`
builds each payload from these models.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from meeting_assistant.api.schemas.runs import Segment, StageInfo


class ManifestEvent(BaseModel):
    """``event: manifest`` -- sent whenever the run's manifest changes."""

    status: str
    stages: list[StageInfo]
    extra: dict[str, Any] = Field(default_factory=dict)


class SegmentsEvent(BaseModel):
    """``event: segments`` -- tagged segments appended since the last event.

    ``start_index`` is the index of ``segments[0]`` in the full transcript, so
    a client can detect a gap (and refetch) instead of silently mis-appending.
    """

    start_index: int
    segments: list[Segment]


class EndEvent(BaseModel):
    """``event: end`` -- no job is active and the run is final; the stream closes."""

    run_id: str


class LevelEvent(BaseModel):
    """``event: level`` on ``GET /api/live/level`` -- the microphone's loudness,
    0 (silence) to 1 (full scale), several times a second."""

    level: float = Field(ge=0, le=1)


# ``event: job`` carries a :class:`meeting_assistant.api.schemas.jobs.Job`.
EVENT_MODELS: tuple[type[BaseModel], ...] = (ManifestEvent, SegmentsEvent, EndEvent, LevelEvent)
