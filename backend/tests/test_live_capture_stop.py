"""Tests for ``record_chunks``'s stop signal and chunk offsets, without a microphone.

Frames come from a scripted source and speech detection is patched to read
the script, so these tests exercise the real chunking state machine -- ring
buffer, trigger, flush -- deterministically. ``frame_source`` exists for
exactly this; the microphone itself remains integration-only.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from meeting_assistant.audio import live_capture
from meeting_assistant.audio.live_capture import record_chunks
from meeting_assistant.audio.vad import VadConfig
from meeting_assistant.audio.wav_io import probe_wav

CFG = VadConfig()  # 30 ms frames, 40-frame ring buffer
FRAME_SEC = CFG.frame_duration_ms / 1000


@pytest.fixture(autouse=True)
def scripted_vad(monkeypatch):
    """A frame is "speech" exactly when its samples are non-zero."""
    monkeypatch.setattr(live_capture, "is_speech", lambda vad, data, cfg: any(data))


def _frame(speech: bool) -> np.ndarray:
    return np.full(CFG.frame_size, 1 if speech else 0, dtype=np.int16)


def _source(script, *, stop_event=None, stop_after=None, interrupt_after=None, closed=None):
    """Yield frames per ``script`` (an iterable of bools)."""

    def frames(_cfg, _device):
        try:
            for i, speech in enumerate(script, start=1):
                if interrupt_after is not None and i > interrupt_after:
                    raise KeyboardInterrupt
                if stop_after is not None and i > stop_after:
                    stop_event.set()
                yield _frame(speech)
        finally:
            if closed is not None:
                closed.append(True)

    return frames


def _record(tmp_path, frames, stop_event=None):
    chunks = []
    stats = record_chunks(
        lambda path, offset: chunks.append((path, offset)),
        tmp_path / "chunks",
        vad_config=CFG,
        stop_event=stop_event,
        frame_source=frames,
    )
    return stats, chunks


def test_stop_event_mid_speech_flushes_the_pending_chunk(tmp_path):
    stop = threading.Event()
    script = [False] * 10 + [True] * 200
    stats, chunks = _record(tmp_path, _source(script, stop_event=stop, stop_after=110), stop)

    assert stats.chunks_saved == 1
    assert len(chunks) == 1
    # Exactly the 110 frames seen before the stop: 10 of pre-roll silence
    # (inside the ring buffer at trigger time) plus 100 of speech.
    assert probe_wav(chunks[0][0])["duration_sec"] == pytest.approx(110 * FRAME_SEC, abs=1e-3)


def test_stop_event_before_any_frame_records_nothing(tmp_path):
    stop = threading.Event()
    stop.set()
    stats, chunks = _record(tmp_path, _source([True] * 100), stop)
    assert chunks == []
    assert stats.chunks_saved == 0


def test_stopping_closes_the_frame_source(tmp_path):
    """Breaking out of the loop must close the generator -- for the real
    microphone that is what exits the `with sd.InputStream(...)` block."""
    stop = threading.Event()
    closed: list[bool] = []
    _record(
        tmp_path,
        _source([True] * 100, stop_event=stop, stop_after=60, closed=closed),
        stop,
    )
    assert closed == [True]


def test_keyboard_interrupt_still_flushes_the_pending_chunk(tmp_path):
    script = [True] * 200
    stats, chunks = _record(tmp_path, _source(script, interrupt_after=90))
    assert stats.chunks_saved == 1
    assert probe_wav(chunks[0][0])["duration_sec"] == pytest.approx(90 * FRAME_SEC, abs=1e-3)


def test_offset_marks_where_the_chunks_audio_begins_not_the_trigger_instant(tmp_path):
    """The chunk includes the ring buffer's pre-roll, so its offset must point
    at the first buffered frame. 100 silent frames, then speech: the trigger
    fires on the 21st speech frame (more than half of the 40-frame ring), when
    the ring holds frames 82-121 -- so the chunk starts at frame 81 (0-based)."""
    stop = threading.Event()
    script = [False] * 100 + [True] * 100
    _, chunks = _record(tmp_path, _source(script, stop_event=stop, stop_after=150), stop)

    assert len(chunks) == 1
    assert chunks[0][1] == pytest.approx((100 + 21 - CFG.ring_buffer_frames) * FRAME_SEC)


def test_a_natural_pause_cuts_a_chunk_with_the_right_offset(tmp_path):
    stop = threading.Event()
    script = [True] * 100 + [False] * 60 + [True] * 100
    _, chunks = _record(tmp_path, _source(script, stop_event=stop, stop_after=250), stop)

    assert len(chunks) == 2
    assert chunks[0][1] == pytest.approx(0.0)
    assert chunks[1][1] > chunks[0][1]
