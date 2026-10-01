"""Live microphone capture, transcribed and diarized incrementally.

This is the fix for the project's original live pipeline, which ran
transcription and diarization directly inside the microphone callback. That
froze audio capture for as long as processing took, and the recording itself
proves it: the legacy ``final_transcript.json`` has segments starting at
3.46s, 55.91s and 102.63s — roughly 45-second holes where the loop was busy
diarizing instead of listening. The fix is a producer-consumer split, not a
faster model.

**Two threads, two owners, no locks.** The main thread is a producer only: it
loads every model *before* recording starts (so the ``pyannote.audio`` import
and its FFmpeg DLL registration happen before any thread exists to race with
it — see :mod:`meeting_assistant.bootstrap.ffmpeg_dll`), then calls
:func:`~meeting_assistant.audio.live_capture.record_chunks` with a callback
that does nothing but ``queue.put(...)``. That callback must return in
microseconds, because the frame-reading loop inside ``record_chunks`` cannot
proceed while it runs — putting anything slower there recreates exactly the
bug this module exists to fix. A single daemon worker thread owns the actual
processing: it pulls one chunk at a time, transcribes, diarizes, resolves
speaker identity, tags language, and stitches it onto the running transcript.

**Exactly one worker, not a pool.** ``faster-whisper`` and pyannote's
``Pipeline``/``Model`` are not documented as thread-safe, and two of them
running concurrently on one CPU would only contend for the same
CTranslate2/torch threads anyway. One worker makes a single-owner invariant
hold without any locking: after startup, only the worker touches the models,
the :class:`~meeting_assistant.diarize.speaker_registry.SpeakerRegistry` and
the :class:`~meeting_assistant.align.stitch.TranscriptStitcher`; the main
thread touches only the queue until the worker has fully stopped, at which
point ownership passes back cleanly. Nothing is ever touched by both threads
at once, so there is nothing to protect with a lock.

**A bad chunk must not end the meeting.** Each chunk's processing is wrapped
in its own ``try``/``except``: one segment that fails to diarize, or a corrupt
chunk file, is logged and skipped, and the worker moves on to the next queued
chunk. If it did not, one bad chunk would silently stop the queue from ever
draining, and every chunk recorded after it would be lost with no error at
all — a variant of the exact original bug, just relocated.

**LLM-backed stages run once, at the end, over the whole meeting** — not per
chunk. Hinglish normalization, summarization and action-item extraction are
soft, Ollama-backed batch stages
(:mod:`meeting_assistant.pipeline.stages`) that already know how to run over a
complete tagged transcript; reusing them here rather than re-implementing a
per-chunk LLM call avoids both duplicating that logic and paying for dozens of
extra round-trips to a local model during a live meeting. They run after the
worker has drained and joined, when the main thread has full transcript
ownership back.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from meeting_assistant import config
from meeting_assistant.align.stitch import TranscriptStitcher
from meeting_assistant.audio.live_capture import RecordingStats, record_chunks
from meeting_assistant.audio.vad import DEFAULT_VAD_CONFIG, VadConfig
from meeting_assistant.diarize.speaker_registry import SpeakerRegistry
from meeting_assistant.language.detection import detect_language_for_segments
from meeting_assistant.llm.client import OllamaClient
from meeting_assistant.logging_setup import attach_run_log, detach_run_log, get_logger
from meeting_assistant.paths import RunPaths, new_run
from meeting_assistant.pipeline.manifest import (
    STAGE_FAILED,
    STAGE_OK,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PARTIAL,
    RunManifest,
)
from meeting_assistant.pipeline.stages import STAGES_BY_NAME, StageContext

log = get_logger(__name__)

# Sentinel telling the worker there will be no more chunks. An ordinary object
# rather than None, so a genuine chunk tuple can never be mistaken for it.
_STOP = object()

# Run once the recording stops, in this order, over the full stitched
# transcript -- the same StageSpec functions the batch pipeline uses. None are
# hard: a live meeting's transcript is worth keeping even if Ollama never
# comes up.
_TAIL_STAGES: tuple[str, ...] = (
    "hinglish",
    "summary",
    "action_items",
    "speaker_stats",
    "metadata",
)


@dataclass
class LiveOptions:
    """User-facing knobs for one live session."""

    num_speakers: int | None = None
    device: int | None = None
    use_registry: bool = True
    vad_config: VadConfig = DEFAULT_VAD_CONFIG


@dataclass
class LiveStats:
    """Counts owned exclusively by the worker thread while it runs.

    The main thread only reads these fields after ``worker_thread.join()``
    has returned, which is what makes reading them without a lock safe --
    by then the worker has stopped touching them.
    """

    chunks_processed: int = 0
    chunks_failed: int = 0
    max_backlog: int = 0
    total_processing_sec: float = 0.0

    def as_manifest_dict(self, recording: RecordingStats) -> dict[str, Any]:
        """Combine with the producer's own counts into one manifest block.

        ``realtime_factor`` -- total processing time divided by total recorded
        audio -- is both the concrete, measurable proof that the drop bug is
        gone (a system that were silently dropping audio would show a
        deceptively *good* factor, since it processed less than it recorded)
        and a genuine result for a CPU-only local system.
        """
        mean_latency = (
            self.total_processing_sec / self.chunks_processed if self.chunks_processed else 0.0
        )
        realtime_factor = (
            self.total_processing_sec / recording.total_audio_sec
            if recording.total_audio_sec
            else 0.0
        )
        return {
            "chunks_recorded": recording.chunks_saved,
            "chunks_discarded": recording.chunks_discarded,
            "chunks_processed": self.chunks_processed,
            "chunks_failed": self.chunks_failed,
            "max_backlog": self.max_backlog,
            "session_duration_sec": round(recording.session_duration_sec, 2),
            "total_audio_sec": round(recording.total_audio_sec, 2),
            "total_processing_sec": round(self.total_processing_sec, 2),
            "mean_chunk_latency_sec": round(mean_latency, 3),
            "realtime_factor": round(realtime_factor, 3),
        }


@dataclass
class _WorkerContext:
    """Everything the worker thread needs, assembled once by the main thread
    before recording starts and never touched by it again afterward."""

    paths: RunPaths
    whisper_model: Any
    diarization_pipeline: Any
    registry: SpeakerRegistry | None
    num_speakers: int | None
    stitcher: TranscriptStitcher
    stats: LiveStats


def _process_chunk(chunk_path: Path, offset_sec: float, wc: _WorkerContext) -> None:
    """Run one chunk through transcription, diarization, speaker resolution,
    language tagging and stitching, then re-dump the running transcript.

    Deliberately does not persist per-chunk transcript/diarization/aligned
    artifacts: those distinctions are meaningful for one pass over one whole
    file (batch mode), but here each chunk's raw ASR and diarization output is
    a transient intermediate that is never independently useful once stitched.
    ``tagged`` is the first artifact that represents the whole meeting on one
    timeline, so it is the one written -- atomically, via ``write_json`` --
    after every chunk, which is what lets a hard kill mid-recording still
    leave a valid, readable partial transcript on disk.
    """
    from meeting_assistant.align.alignment import (
        UNKNOWN_SPEAKER,
        align_transcript,
        merge_consecutive_same_speaker,
    )
    from meeting_assistant.asr.whisper_asr import transcribe_audio
    from meeting_assistant.diarize.pyannote_diarizer import diarize_audio
    from meeting_assistant.io_utils import write_json

    transcript = transcribe_audio(wc.whisper_model, chunk_path).segments
    diarization = diarize_audio(
        wc.diarization_pipeline, chunk_path, num_speakers=wc.num_speakers
    ).segments
    aligned = align_transcript(transcript, diarization)
    merged = merge_consecutive_same_speaker(aligned)

    if wc.registry is not None:
        local_labels = {s["speaker"] for s in merged if s["speaker"] != UNKNOWN_SPEAKER}
        # A chunk's local diarization reporting more than one label is exactly
        # the case resolve_chunk's single whole-chunk vector gets wrong (see
        # SpeakerRegistry's docstring); resolve_segments costs one embedding
        # call per label instead of per chunk, but is correct either way, so it
        # is only worth the extra cost when resolve_chunk would be unsound.
        resolve = (
            wc.registry.resolve_segments if len(local_labels) > 1 else wc.registry.resolve_chunk
        )
        merged = resolve(chunk_path, merged)

    tagged = detect_language_for_segments(merged)
    wc.stitcher.add_chunk(tagged, offset_sec)
    write_json(wc.paths.artifact("tagged"), wc.stitcher.get_full_transcript())


def _worker_loop(q: queue.Queue, wc: _WorkerContext) -> None:
    """Consume chunks until :data:`_STOP`. Runs entirely on the worker thread."""
    while True:
        item = q.get()
        if item is _STOP:
            q.task_done()
            return

        chunk_path, offset_sec = item
        # +1: the item just dequeued was, an instant ago, also sitting in the
        # backlog: qsize() alone would undercount by exactly the one chunk
        # currently being processed.
        wc.stats.max_backlog = max(wc.stats.max_backlog, q.qsize() + 1)

        started = time.perf_counter()
        try:
            _process_chunk(chunk_path, offset_sec, wc)
        except Exception:  # noqa: BLE001 -- one bad chunk must not stop the queue draining
            wc.stats.chunks_failed += 1
            log.exception("Failed to process chunk %s; continuing.", chunk_path)
        finally:
            wc.stats.chunks_processed += 1
            wc.stats.total_processing_sec += time.perf_counter() - started
            q.task_done()


def _run_tail_stages(ctx: StageContext, manifest: RunManifest, paths: RunPaths) -> None:
    """Run the LLM-backed and statistics stages once, over the full transcript.

    Mirrors the per-stage try/except and manifest recording in
    :func:`meeting_assistant.pipeline.batch.run_batch`, simplified because none
    of these stages are hard and none has an unmet ``requires`` to check here --
    ``tagged`` is guaranteed to exist by the time this is called.
    """
    for name in _TAIL_STAGES:
        stage = STAGES_BY_NAME[name]
        log.info("Running stage: %s", stage.name)
        started = time.perf_counter()
        try:
            counts = stage.fn(ctx)
        except Exception as exc:  # noqa: BLE001 -- recorded and classified, not fatal to the run
            elapsed = time.perf_counter() - started
            log.exception("Stage %s failed after %.1fs", stage.name, elapsed)
            manifest.record_stage(stage.name, STAGE_FAILED, seconds=elapsed, error=str(exc))
        else:
            elapsed = time.perf_counter() - started
            manifest.record_stage(
                stage.name,
                STAGE_OK,
                seconds=elapsed,
                outputs=[str(paths.artifact(stage.name))],
                counts=counts,
            )
            log.info("Completed stage %s in %.1fs", stage.name, elapsed)


def create_live_run() -> RunPaths:
    """Create a live run directory and its initial manifest, without recording.

    Lets the HTTP API return a ``run_id`` before the recording thread starts.
    """
    paths = new_run("live")
    RunManifest.start(paths, mode="live")
    return paths


def run_live(
    opts: LiveOptions | None = None,
    *,
    paths: RunPaths | None = None,
    stop_event: threading.Event | None = None,
) -> RunPaths:
    """Record from the microphone and process it incrementally until stopped.

    Runs until interrupted with Ctrl+C, or until ``stop_event`` is set (how the
    HTTP API stops it). A second Ctrl+C while queued chunks are still draining
    abandons whatever has not yet been processed rather than waiting
    indefinitely -- the transcript up to that point has already been saved
    (every chunk re-dumps it atomically), so nothing already processed is
    lost, only whatever was still queued.

    Args:
        paths: an existing run from :func:`create_live_run`; a new one is
            created when omitted.

    Returns:
        The run's :class:`~meeting_assistant.paths.RunPaths`. Check
        ``paths.manifest_path`` for the final status, exactly as with
        :func:`meeting_assistant.pipeline.batch.run_batch`.

    Raises:
        ConfigError: a hard prerequisite (FFmpeg DLLs, the Hugging Face token)
            is missing. Checked before anything is loaded or recorded, so
            failure is immediate rather than after minutes of a meeting.
    """
    opts = opts or LiveOptions()
    config.validate_config(require_hf_token=True, require_ffmpeg=True, require_ollama=False)

    paths = paths or create_live_run()
    manifest = RunManifest.load(paths)
    log.info("Run %s started", paths.run_id)
    log_handler = attach_run_log(paths.log_path)

    try:
        # Every model loads here, on the main thread, before recording starts
        # and before the worker thread exists -- see the module docstring for
        # why that ordering (not just the threading split itself) matters.
        from meeting_assistant.asr.whisper_asr import load_model
        from meeting_assistant.diarize.pyannote_diarizer import load_pipeline

        whisper_model = load_model()
        diarization_pipeline = load_pipeline(config.HF_TOKEN)

        registry: SpeakerRegistry | None = None
        if opts.use_registry:
            from meeting_assistant.diarize.embeddings import (
                build_inference,
                embed_window,
                load_embedding_model,
            )

            inference = build_inference(load_embedding_model())

            def embedder(audio_path: str | Path, start: float, end: float):
                return embed_window(inference, audio_path, start, end)

            registry = SpeakerRegistry(embedder=embedder)

        stats = LiveStats()
        wc = _WorkerContext(
            paths=paths,
            whisper_model=whisper_model,
            diarization_pipeline=diarization_pipeline,
            registry=registry,
            num_speakers=opts.num_speakers,
            stitcher=TranscriptStitcher(),
            stats=stats,
        )

        q: queue.Queue = queue.Queue()
        worker = threading.Thread(target=_worker_loop, args=(q, wc), daemon=True)
        worker.start()

        def enqueue(chunk_path: Path, offset_sec: float) -> None:
            q.put((chunk_path, offset_sec))

        recording = record_chunks(
            enqueue,
            paths.chunks_dir,
            vad_config=opts.vad_config,
            device=opts.device,
            stop_event=stop_event,
        )

        q.put(_STOP)
        backlog = q.qsize()
        if backlog > 1:
            log.info("Draining %d queued chunk(s)...", backlog - 1)
        try:
            worker.join()
        except KeyboardInterrupt:
            log.warning(
                "Second interrupt: abandoning queued chunks; keeping what was "
                "already processed and saved."
            )

        manifest.set_extra("live_stats", stats.as_manifest_dict(recording))

        if not paths.has("tagged"):
            log.warning("No speech was captured; nothing to process.")
            manifest.set_status(STATUS_FAILED)
            return paths

        ctx = StageContext(
            paths=paths,
            audio_path=None,
            num_speakers=opts.num_speakers,
            run_started_at=datetime.now(),
            llm=OllamaClient(),
        )
        _run_tail_stages(ctx, manifest, paths)

        statuses = {manifest.stage_status(name) for name in _TAIL_STAGES}
        manifest.set_status(STATUS_COMPLETED if statuses == {STAGE_OK} else STATUS_PARTIAL)
        log.info("Run %s finished: %s", paths.run_id, manifest.status)

    except Exception as exc:
        # E.g. a model failed to load before recording started. Without this
        # the manifest would sit at its initial "partial" forever, which reads
        # as "interrupted, resumable" rather than "never worked".
        manifest.set_extra("error", f"{type(exc).__name__}: {exc}")
        manifest.set_status(STATUS_FAILED)
        raise

    finally:
        detach_run_log(log_handler)

    return paths
