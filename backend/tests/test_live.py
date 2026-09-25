"""Tests for the live pipeline's orchestration: worker draining, per-chunk
failure isolation, backlog tracking, and the tail-stage runner.

``run_live`` itself needs a real microphone (via ``sounddevice``) and is not
exercised here, for the same reason ``record_chunks`` and ``load_pipeline``
are not unit-tested directly -- see ``test_diarizer.py``. What is genuinely
unit-testable without any of that is the mechanism this whole phase exists to
get right: does the worker drain every queued chunk, in order, without one
bad chunk silently stopping the rest, and does it track backlog honestly. That
is the actual fix for the original live pipeline's ~45-second audio-dropping
bug, and it is pure queue/thread orchestration, independent of what a chunk's
processing actually does.

``_process_chunk`` -- the real transcribe/diarize/align/resolve/tag/stitch
chain -- is exercised end-to-end on real, independently-sliced audio in one
``@pytest.mark.integration`` test at the bottom of this module, the same
real-audio pattern used for the diarizer and the speaker registry.
"""

from __future__ import annotations

import queue

import pytest

from meeting_assistant.align.stitch import TranscriptStitcher
from meeting_assistant.audio.live_capture import RecordingStats
from meeting_assistant.paths import new_run
from meeting_assistant.pipeline import live as live_mod
from meeting_assistant.pipeline.live import _STOP, LiveStats, _WorkerContext
from meeting_assistant.pipeline.manifest import STAGE_FAILED, STAGE_OK, RunManifest
from meeting_assistant.pipeline.stages import StageSpec


# ---------------------------------------------------------------------------
# LiveStats.as_manifest_dict
# ---------------------------------------------------------------------------
def test_as_manifest_dict_computes_mean_latency_and_realtime_factor():
    stats = LiveStats(
        chunks_processed=4, chunks_failed=1, max_backlog=3, total_processing_sec=8.0
    )
    recording = RecordingStats(
        chunks_saved=4, chunks_discarded=1, total_audio_sec=16.0, session_duration_sec=20.0
    )

    result = stats.as_manifest_dict(recording)

    assert result["chunks_recorded"] == 4
    assert result["chunks_discarded"] == 1
    assert result["chunks_processed"] == 4
    assert result["chunks_failed"] == 1
    assert result["max_backlog"] == 3
    assert result["mean_chunk_latency_sec"] == pytest.approx(2.0)
    assert result["realtime_factor"] == pytest.approx(0.5)


def test_as_manifest_dict_handles_zero_chunks_without_dividing_by_zero():
    stats = LiveStats()
    recording = RecordingStats()
    result = stats.as_manifest_dict(recording)
    assert result["mean_chunk_latency_sec"] == 0.0
    assert result["realtime_factor"] == 0.0


# ---------------------------------------------------------------------------
# _worker_loop
# ---------------------------------------------------------------------------
def _worker_context(tmp_path):
    paths = new_run("live", runs_dir=tmp_path / "runs")
    return _WorkerContext(
        paths=paths,
        whisper_model=None,
        diarization_pipeline=None,
        registry=None,
        num_speakers=None,
        stitcher=TranscriptStitcher(),
        stats=LiveStats(),
    )


def test_worker_processes_every_queued_chunk_in_order(tmp_path, monkeypatch):
    wc = _worker_context(tmp_path)
    processed = []
    monkeypatch.setattr(
        live_mod, "_process_chunk", lambda path, offset, _wc: processed.append((path, offset))
    )

    q: queue.Queue = queue.Queue()
    for i in range(3):
        q.put((f"chunk{i}.wav", float(i)))
    q.put(_STOP)

    live_mod._worker_loop(q, wc)

    assert processed == [("chunk0.wav", 0.0), ("chunk1.wav", 1.0), ("chunk2.wav", 2.0)]
    assert wc.stats.chunks_processed == 3
    assert wc.stats.chunks_failed == 0


def test_a_failing_chunk_is_recorded_and_the_worker_continues(tmp_path, monkeypatch):
    """The core guarantee: one bad chunk must not stop the rest from draining --
    the original bug was audio silently disappearing with no trace at all."""
    wc = _worker_context(tmp_path)
    processed = []

    def fake_process(chunk_path, offset_sec, _wc):
        if chunk_path == "bad.wav":
            raise RuntimeError("boom")
        processed.append(chunk_path)

    monkeypatch.setattr(live_mod, "_process_chunk", fake_process)

    q: queue.Queue = queue.Queue()
    q.put(("good1.wav", 0.0))
    q.put(("bad.wav", 1.0))
    q.put(("good2.wav", 2.0))
    q.put(_STOP)

    live_mod._worker_loop(q, wc)

    assert processed == ["good1.wav", "good2.wav"]
    assert wc.stats.chunks_processed == 3  # attempted, including the failed one
    assert wc.stats.chunks_failed == 1


def test_max_backlog_reflects_the_deepest_queue_seen(tmp_path, monkeypatch):
    wc = _worker_context(tmp_path)
    monkeypatch.setattr(live_mod, "_process_chunk", lambda path, offset, _wc: None)

    q: queue.Queue = queue.Queue()
    for i in range(5):
        q.put((f"chunk{i}.wav", float(i)))
    q.put(_STOP)

    live_mod._worker_loop(q, wc)

    # This test enqueues everything -- 5 chunks and _STOP -- before the worker
    # ever calls get(), so the first dequeue sees all 6 items still sitting in
    # the queue (5 remaining plus the 1 just taken). In real use _STOP is only
    # enqueued once recording has fully stopped, so it never inflates a
    # mid-recording backlog reading the way this synchronous test's setup does.
    assert wc.stats.max_backlog == 6


def test_total_processing_sec_accumulates_across_chunks(tmp_path, monkeypatch):
    import time as time_mod

    wc = _worker_context(tmp_path)
    monkeypatch.setattr(live_mod, "_process_chunk", lambda path, offset, _wc: time_mod.sleep(0.01))

    q: queue.Queue = queue.Queue()
    q.put(("a.wav", 0.0))
    q.put(("b.wav", 1.0))
    q.put(_STOP)

    live_mod._worker_loop(q, wc)
    assert wc.stats.total_processing_sec >= 0.02


def test_worker_returns_immediately_on_an_empty_queue_with_just_stop(tmp_path, monkeypatch):
    wc = _worker_context(tmp_path)
    called = []
    monkeypatch.setattr(live_mod, "_process_chunk", lambda path, offset, _wc: called.append(1))

    q: queue.Queue = queue.Queue()
    q.put(_STOP)

    live_mod._worker_loop(q, wc)  # must return, not hang

    assert called == []
    assert wc.stats.chunks_processed == 0


# ---------------------------------------------------------------------------
# _run_tail_stages
# ---------------------------------------------------------------------------
def _stub_stage(name, *, fails=False):
    def fn(ctx):  # noqa: ARG001 -- the fake stages never touch ctx
        if fails:
            raise RuntimeError(f"{name} failed on purpose")
        return {"stub": name}

    return StageSpec(name=name, requires=(), fn=fn)


def test_run_tail_stages_records_every_stage_as_ok(tmp_path, monkeypatch):
    paths = new_run("live", runs_dir=tmp_path / "runs")
    manifest = RunManifest.start(paths, mode="live")
    monkeypatch.setattr(
        live_mod, "STAGES_BY_NAME", {name: _stub_stage(name) for name in live_mod._TAIL_STAGES}
    )

    live_mod._run_tail_stages(ctx=object(), manifest=manifest, paths=paths)

    for name in live_mod._TAIL_STAGES:
        assert manifest.stage_status(name) == STAGE_OK


def test_run_tail_stages_a_failure_does_not_stop_later_stages(tmp_path, monkeypatch):
    """Mirrors the batch orchestrator's soft-failure isolation: an Ollama
    outage midway through the tail must not cost the stages after it."""
    paths = new_run("live", runs_dir=tmp_path / "runs")
    manifest = RunManifest.start(paths, mode="live")
    monkeypatch.setattr(
        live_mod,
        "STAGES_BY_NAME",
        {name: _stub_stage(name, fails=(name == "summary")) for name in live_mod._TAIL_STAGES},
    )

    live_mod._run_tail_stages(ctx=object(), manifest=manifest, paths=paths)

    assert manifest.stage_status("hinglish") == STAGE_OK
    assert manifest.stage_status("summary") == STAGE_FAILED
    assert manifest.stage_status("action_items") == STAGE_OK
    assert manifest.stage_status("speaker_stats") == STAGE_OK
    assert manifest.stage_status("metadata") == STAGE_OK


# ---------------------------------------------------------------------------
# Real audio, real models -- the actual per-chunk pipeline, without a microphone
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_process_chunk_end_to_end_on_two_independently_sliced_chunks(tmp_path, slice_wav):
    """Runs the real ``_process_chunk`` body -- transcribe, diarize, align,
    merge, resolve speaker identity, tag language, stitch -- on two chunks cut
    from ``data/audio/test_hindi.wav``, exactly as ``record_chunks`` would
    hand them to the worker one at a time. Not a microphone: that boundary
    (``record_chunks`` itself) is the one piece of live capture this project
    does not unit-test, matching the diarizer's own real-audio convention.
    """
    from pathlib import Path

    from meeting_assistant import config
    from meeting_assistant.diarize.pyannote_diarizer import load_pipeline
    from meeting_assistant.io_utils import read_json

    source = Path(config.AUDIO_DIR) / "test_hindi.wav"
    if not source.exists():
        pytest.skip(f"integration fixture not present: {source}")

    from meeting_assistant.asr.whisper_asr import load_model

    paths = new_run("live", runs_dir=tmp_path / "runs")
    wc = _WorkerContext(
        paths=paths,
        whisper_model=load_model(),
        diarization_pipeline=load_pipeline(config.HF_TOKEN),
        registry=None,  # registry mechanics are covered by test_speaker_registry.py
        num_speakers=None,
        stitcher=TranscriptStitcher(),
        stats=LiveStats(),
    )

    chunk1 = slice_wav(source, tmp_path / "chunk1.wav", 0.0, 6.0)
    chunk2 = slice_wav(source, tmp_path / "chunk2.wav", 6.0, 11.4)

    live_mod._process_chunk(chunk1, 0.0, wc)
    live_mod._process_chunk(chunk2, 6.0, wc)

    assert paths.has("tagged")
    tagged = read_json(paths.artifact("tagged"))
    assert tagged, "no segments were produced across either chunk"
    assert all("language" in segment for segment in tagged)
    assert all("speaker" in segment for segment in tagged)
    # The second chunk's segments must land on the meeting timeline, not
    # chunk2's own zero-based clock -- proof offset_sec was actually applied.
    assert max(s["end"] for s in tagged) > 6.0
