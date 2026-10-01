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
import threading
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


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------
API_TOKEN = "test-token-" + "x" * 32


class StubPipeline:
    """Stand-in for ``run_batch``/``run_live`` behind the API's JobManager.

    Writes a manifest stage and a couple of artifacts the way a real run
    would, without loading a model. ``gate`` lets a test hold a batch job in
    ``running`` to observe queueing; ``fail`` makes the next job raise.
    """

    def __init__(self):
        self.batch_calls: list = []
        self.live_calls: list = []
        self.gate: threading.Event | None = None
        self.fail = False

    def run_batch(self, audio_path, opts):
        from meeting_assistant.io_utils import write_json
        from meeting_assistant.paths import open_run
        from meeting_assistant.pipeline.manifest import RunManifest

        self.batch_calls.append(opts)
        if self.gate is not None:
            self.gate.wait(timeout=10)
        if self.fail:
            raise RuntimeError("stub pipeline failed")

        paths = open_run(opts.resume_run_id)
        manifest = RunManifest.load(paths)
        write_json(
            paths.artifact("tagged"),
            [
                {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00", "text": "namaste",
                 "language": "Hindi"},
                {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_01", "text": "hello",
                 "language": "English"},
            ],
        )
        write_json(
            paths.artifact("summary"),
            {"summary": "A greeting.", "highlights": ["hello"], "key_decisions": []},
        )
        manifest.record_stage("tagged", "ok", seconds=0.1, counts={"segments": 2})
        manifest.record_stage("summary", "ok", seconds=0.1)
        manifest.set_status("completed")
        return paths

    def run_live(self, opts, *, paths, stop_event):
        from meeting_assistant.io_utils import write_json
        from meeting_assistant.pipeline.manifest import RunManifest

        self.live_calls.append(opts)
        segments = []
        # One "chunk" every 50 ms until stopped, the way the real worker
        # re-dumps the stitched transcript after each chunk.
        while not stop_event.wait(timeout=0.05):
            segments.append(
                {"start": float(len(segments)), "end": len(segments) + 1.0,
                 "speaker": "SPEAKER_G01", "text": f"chunk {len(segments)}"}
            )
            write_json(paths.artifact("tagged"), segments)
            if len(segments) >= 200:
                break
        manifest = RunManifest.load(paths)
        manifest.set_extra("live_stats", {"chunks_recorded": len(segments)})
        manifest.set_status("completed")
        return paths


@pytest.fixture
def api_env(tmp_path, monkeypatch):
    """Point every data location at tmp_path and set a known API token."""
    from meeting_assistant import config

    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "AUDIO_DIR", tmp_path / "audio")
    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(config, "INDEX_DB_PATH", tmp_path / "index.sqlite")
    monkeypatch.setattr(config, "API_TOKEN", API_TOKEN)
    (tmp_path / "audio").mkdir()
    return tmp_path


@pytest.fixture
def stub_pipeline():
    return StubPipeline()


@pytest.fixture
def client(api_env, stub_pipeline):
    """An authenticated TestClient over an app whose jobs run the stub pipeline."""
    from fastapi.testclient import TestClient

    from meeting_assistant.api.app import create_app
    from meeting_assistant.api.jobs import JobManager

    jobs = JobManager(run_batch=stub_pipeline.run_batch, run_live=stub_pipeline.run_live)
    # An empty UI directory, so tests never depend on whether the real
    # frontend has been built.
    app = create_app(jobs=jobs, preload_models=False, frontend_dist=api_env / "no-ui")
    with TestClient(app, headers={"Authorization": f"Bearer {API_TOKEN}"}) as test_client:
        yield test_client
    if stub_pipeline.gate is not None:
        stub_pipeline.gate.set()


@pytest.fixture
def audio_file(api_env):
    """A short real WAV in the patched audio directory."""
    import numpy as np

    from meeting_assistant.audio.wav_io import save_wav

    return save_wav(api_env / "audio" / "meeting.wav", np.zeros(16000, dtype=np.int16), 16000)


@pytest.fixture
def wait_for_job(client):
    """Poll a run until its job reaches one of ``states``; return the run detail."""
    import time

    def wait(run_id, *, states=("finished", "failed"), timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            detail = client.get(f"/api/runs/{run_id}").json()
            if detail.get("job") and detail["job"]["state"] in states:
                return detail
            time.sleep(0.02)
        raise AssertionError(f"job for {run_id} never reached {states}")

    return wait
