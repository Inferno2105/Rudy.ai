"""Shared fixtures.

The default test run must stay hermetic and fast: no model loading, no Ollama,
no microphone, no network. That is achievable because the logic worth testing —
timestamp overlap, script classification, statistics, speaker matching, JSON
recovery — is pure, and because every module that needs a model or an LLM takes
it as an argument rather than constructing one. Anything that genuinely needs a
model is marked ``slow`` or ``integration`` and excluded by default.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def slice_wav():
    """Cut ``[start_sec, end_sec)`` out of a WAV file into a new one.

    Used by the real-audio integration tests (speaker registry, live
    pipeline) to build independently-diarizable chunks out of one longer
    fixture recording -- the same situation live capture puts each chunk in,
    without needing a microphone or ffmpeg to produce it.
    """

    def cut(source: Path, dst_path: Path, start_sec: float, end_sec: float) -> Path:
        with wave.open(str(source), "rb") as src:
            channels = src.getnchannels()
            sampwidth = src.getsampwidth()
            rate = src.getframerate()
            src.setpos(int(start_sec * rate))
            frames = src.readframes(int((end_sec - start_sec) * rate))
        with wave.open(str(dst_path), "wb") as out:
            out.setnchannels(channels)
            out.setsampwidth(sampwidth)
            out.setframerate(rate)
            out.writeframes(frames)
        return dst_path

    return cut


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    """An isolated runs directory, so tests never touch the real data/runs."""
    path = tmp_path / "runs"
    path.mkdir()
    return path


@pytest.fixture
def whisper_segments() -> list[dict]:
    """Transcript segments in the shape the ASR stage emits."""
    return [
        {"start": 0.0, "end": 2.5, "text": "Good morning everyone."},
        {"start": 2.6, "end": 5.0, "text": "Aaj hum project discuss karenge."},
        {"start": 5.2, "end": 7.8, "text": "Backend is almost done."},
    ]


@pytest.fixture
def speaker_segments() -> list[dict]:
    """Diarization turns that overlap the transcript segments above."""
    return [
        {"start": 0.0, "end": 2.4, "speaker": "SPEAKER_00"},
        {"start": 2.5, "end": 5.1, "speaker": "SPEAKER_01"},
        {"start": 5.1, "end": 8.0, "speaker": "SPEAKER_00"},
    ]


@pytest.fixture
def aligned_segments() -> list[dict]:
    """Speaker-attributed segments, as produced after alignment."""
    return [
        {"start": 0.0, "end": 2.5, "speaker": "SPEAKER_00", "text": "Good morning everyone."},
        {"start": 2.6, "end": 5.0, "speaker": "SPEAKER_01", "text": "Aaj hum discuss karenge."},
        {"start": 5.2, "end": 7.8, "speaker": "SPEAKER_00", "text": "Backend is almost done."},
    ]


@pytest.fixture
def synthetic_tagged_segments() -> list[dict]:
    """A 22-segment hand-authored transcript, used only as test input.

    This is the file that caused real trouble: it was written by hand to exercise
    the summarization and action-item stages, and its derived outputs then sat in
    the output directory looking exactly like genuine pipeline results. It is
    genuinely useful for testing the stages that need a realistic multi-speaker
    transcript without any audio, so it is kept — under a filename that makes its
    provenance impossible to mistake.
    """
    path = FIXTURES / "synthetic_tagged_22seg.json"
    if not path.exists():
        pytest.skip(f"fixture not present: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


class FakeOllamaTransport:
    """Stand-in for ``ollama.Client``, returning scripted replies.

    Records the prompts it received so a test can assert on retry behaviour —
    specifically that a retry restates the JSON requirement rather than resending
    an identical prompt.
    """

    def __init__(self, replies: list[str]):
        self._replies = list(replies)
        self.prompts: list[str] = []

    def chat(self, *, model, messages, options=None):  # noqa: ARG002
        self.prompts.append(messages[-1]["content"])
        content = self._replies.pop(0) if self._replies else ""
        return {
            "message": {"content": content},
            "prompt_eval_count": 11,
            "eval_count": 7,
        }


@pytest.fixture
def fake_llm():
    """Build an OllamaClient wired to scripted replies, with no server."""

    def build(replies: list[str]):
        from meeting_assistant.llm.client import OllamaClient

        client = OllamaClient()
        transport = FakeOllamaTransport(replies)
        client._client = transport
        return client, transport

    return build
