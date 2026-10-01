"""Response models for health, audio files, uploads and input devices."""

from __future__ import annotations

from pydantic import BaseModel


class Health(BaseModel):
    version: str
    ok: bool
    problems: list[str]


class AudioFile(BaseModel):
    name: str
    size_bytes: int
    duration_sec: float | None = None


class UploadResult(AudioFile):
    sha256: str
    already_present: bool


class InputDevice(BaseModel):
    index: int
    name: str
    channels: int
    default_samplerate: float
    is_default: bool


class IndexRebuildResult(BaseModel):
    indexed: int
    total: int
