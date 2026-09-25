"""Live microphone capture with VAD-triggered chunk boundaries.

Records continuously, classifies each short frame as speech or silence via
:mod:`meeting_assistant.audio.vad`, and cuts a new chunk whenever enough recent
silence accumulates to mark the end of an utterance. See that module's docstring
for why a trained classifier is used here rather than an energy threshold.

This module only records and chunks. It has no knowledge of transcription or
diarization, and does no work on the returned audio beyond writing it to disk —
that separation is what lets :mod:`meeting_assistant.pipeline.live` run the
actual (slow) processing on a different thread from the one calling
:func:`record_chunks`, so recording is never blocked waiting for a chunk to be
transcribed. See that module for the full explanation of why this split exists:
an earlier version of the live pipeline ran the expensive work directly inside
the ``on_chunk_ready`` callback, which froze audio capture for as long as
processing took and silently dropped whatever was said during that window.
"""

from __future__ import annotations

import collections
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from meeting_assistant.audio.vad import DEFAULT_VAD_CONFIG, VadConfig, create_vad, is_speech
from meeting_assistant.audio.wav_io import save_wav
from meeting_assistant.logging_setup import get_logger

log = get_logger(__name__)

OnChunkReady = Callable[[Path, float], None]


@dataclass
class RecordingStats:
    """Counts recorded during one recording session, for the run manifest."""

    chunks_saved: int = 0
    chunks_discarded: int = 0
    total_audio_sec: float = 0.0
    session_duration_sec: float = 0.0

    def as_manifest_dict(self) -> dict[str, Any]:
        return {
            "chunks_saved": self.chunks_saved,
            "chunks_discarded": self.chunks_discarded,
            "total_audio_sec": round(self.total_audio_sec, 2),
            "session_duration_sec": round(self.session_duration_sec, 2),
        }


def record_chunks(
    on_chunk_ready: OnChunkReady,
    chunk_dir: str | Path,
    *,
    vad_config: VadConfig = DEFAULT_VAD_CONFIG,
    device: int | None = None,
) -> RecordingStats:
    """Record from the microphone, cutting a chunk at each natural pause.

    Runs until interrupted (Ctrl+C). The interrupt is caught here so any
    in-progress chunk can be flushed before returning, rather than discarding
    whatever was being said at the moment the user chose to stop.

    Args:
        on_chunk_ready: called as ``(chunk_path, offset_sec)`` once a chunk is
            written. ``offset_sec`` is how many seconds into this recording
            session the chunk *started*, which stitching needs in order to place
            the chunk's own zero-based timestamps onto the shared meeting
            timeline. **Must return quickly** — anything slow here (transcribing
            the chunk, for instance) blocks the next frame read and starts
            dropping audio. Callers that need to do slow work per chunk should
            hand it off to a queue and a worker thread rather than doing it
            inline; see :mod:`meeting_assistant.pipeline.live`.
        chunk_dir: where chunk WAV files are written. Required — the caller owns
            a run directory and decides where its chunks live; there is no
            project-wide default to fall back to.
        device: ``sounddevice`` input device index, or ``None`` for the system
            default.

    Returns:
        Counts for the session, for inclusion in the run manifest.
    """
    import sounddevice as sd

    chunk_dir = Path(chunk_dir)
    chunk_dir.mkdir(parents=True, exist_ok=True)

    vad = create_vad(vad_config)
    ring_buffer: collections.deque[tuple[np.ndarray, bool]] = collections.deque(
        maxlen=vad_config.ring_buffer_frames
    )
    current_chunk_frames: list[np.ndarray] = []
    triggered = False

    stats = RecordingStats()
    recording_start = time.time()
    chunk_index = 0
    chunk_start_time = 0.0

    log.info(
        "Listening (device=%s)... Ctrl+C to stop.",
        device if device is not None else "default",
    )

    def frames():
        with sd.InputStream(
            samplerate=vad_config.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=vad_config.frame_size,
            device=device,
        ) as stream:
            while True:
                frame, _ = stream.read(vad_config.frame_size)
                yield frame[:, 0]  # mono

    def flush_chunk(pending_frames: list[np.ndarray]) -> None:
        nonlocal chunk_index
        audio = np.concatenate(pending_frames)
        duration = len(audio) / vad_config.sample_rate

        if duration < vad_config.min_chunk_duration_sec:
            stats.chunks_discarded += 1
            log.debug("Discarded short chunk (%.1fs, likely noise)", duration)
            return

        chunk_index += 1
        chunk_path = chunk_dir / f"chunk_{chunk_index:04d}.wav"
        save_wav(chunk_path, audio, vad_config.sample_rate)
        stats.chunks_saved += 1
        stats.total_audio_sec += duration
        log.info("Saved chunk %d (%.1fs) -> %s", chunk_index, duration, chunk_path)
        on_chunk_ready(chunk_path, chunk_start_time)

    try:
        for frame in frames():
            speech = is_speech(vad, frame.tobytes(), vad_config)

            if not triggered:
                ring_buffer.append((frame, speech))
                voiced = sum(1 for _, s in ring_buffer if s)
                # Enough of the recent buffer is speech: start a chunk, and
                # include the buffered frames leading up to the trigger so the
                # onset of speech is not clipped.
                if voiced > 0.5 * ring_buffer.maxlen:
                    triggered = True
                    chunk_start_time = time.time() - recording_start
                    current_chunk_frames = [f for f, _ in ring_buffer]
                    ring_buffer.clear()
            else:
                current_chunk_frames.append(frame)
                ring_buffer.append((frame, speech))
                unvoiced = sum(1 for _, s in ring_buffer if not s)
                duration_so_far = len(current_chunk_frames) * vad_config.frame_duration_ms / 1000

                pause_reached = unvoiced > 0.9 * ring_buffer.maxlen
                max_duration_reached = duration_so_far >= vad_config.max_chunk_duration_sec

                if pause_reached or max_duration_reached:
                    triggered = False
                    ring_buffer.clear()
                    flush_chunk(current_chunk_frames)
                    current_chunk_frames = []

    except KeyboardInterrupt:
        log.info("Stopped listening.")
        if current_chunk_frames:
            flush_chunk(current_chunk_frames)

    stats.session_duration_sec = time.time() - recording_start
    return stats
