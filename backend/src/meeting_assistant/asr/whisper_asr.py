"""Speech recognition via faster-whisper.

``large-v3`` is the default model size, not a placeholder choice. During
exploration, ``medium`` produced genuine word-level errors on Hindi and
code-mixed audio — confusing "kaun" with "kyun", mangling "hopefully" — that no
amount of downstream processing could repair, since normalization and
summarization both trust the ASR output as ground truth for what was said.
Switching to ``large-v3`` resolved it. The comparison is kept as an evaluation
ablation (see ``docs/evaluation.md``) rather than asserted from memory, but the
default reflects what was actually observed.

Language is left as ``None`` (auto-detect) by default rather than forced to
``hi`` or ``en``, because forcing a single language on genuinely code-mixed audio
degrades whichever language segment doesn't match the forced setting — Whisper
will contort non-matching speech into the forced language's phonetics rather than
transcribing it faithfully.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meeting_assistant import config
from meeting_assistant.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class TranscriptionResult:
    """Segments plus the metadata needed to judge and report on the run."""

    segments: list[dict[str, Any]]
    detected_language: str | None
    language_probability: float | None
    duration_sec: float
    elapsed_sec: float

    @property
    def realtime_factor(self) -> float:
        """Processing time divided by audio duration. Below 1.0 is faster than real time.

        A reportable system metric for a CPU-only local pipeline — "how long does
        an hour of audio take to transcribe on this hardware" is a genuine finding,
        not an implementation detail.
        """
        if self.duration_sec <= 0:
            return 0.0
        return round(self.elapsed_sec / self.duration_sec, 3)

    def as_manifest_dict(self) -> dict[str, Any]:
        return {
            "segments": len(self.segments),
            "detected_language": self.detected_language,
            "language_probability": self.language_probability,
            "audio_duration_sec": round(self.duration_sec, 2),
            "elapsed_sec": round(self.elapsed_sec, 2),
            "realtime_factor": self.realtime_factor,
        }


def load_model(
    model_size: str | None = None,
    device: str | None = None,
    compute_type: str | None = None,
):
    """Load a faster-whisper model once, for reuse across many transcriptions.

    Loading is the expensive step (seconds to tens of seconds depending on model
    size), so callers — the batch orchestrator, the live pipeline — load once at
    startup and pass the model into :func:`transcribe_audio` repeatedly, rather
    than reloading per file or per chunk.
    """
    from faster_whisper import WhisperModel

    model_size = model_size or config.WHISPER_MODEL_SIZE
    device = device or config.WHISPER_DEVICE
    compute_type = compute_type or config.WHISPER_COMPUTE_TYPE

    log.info(
        "Loading faster-whisper model %s (device=%s, compute_type=%s)",
        model_size,
        device,
        compute_type,
    )
    started = time.perf_counter()
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    log.info("Model loaded in %.1fs", time.perf_counter() - started)
    return model


def transcribe_audio(
    model: Any,
    audio_path: str | Path,
    *,
    language: str | None = None,
    beam_size: int = 5,
    vad_filter: bool = True,
    initial_prompt: str | None = None,
) -> TranscriptionResult:
    """Transcribe one audio file into timestamped segments.

    Args:
        model: a loaded model from :func:`load_model`.
        language: ISO 639-1 code, or ``None`` to auto-detect (default, and
            recommended for code-mixed audio — see the module docstring).
        beam_size: search width. 5 is faster-whisper's own recommended default
            and was not observed to need changing during testing.
        vad_filter: Whisper's own internal VAD, which suppresses hallucinated
            text over silence. This is independent of and complementary to the
            project's own ``webrtcvad``-based chunk boundaries in live capture —
            that VAD decides *where to cut*, this one decides *what to skip*
            within a single file.
        initial_prompt: optional vocabulary/spelling hint text, fed to Whisper's
            decoder as context. Not used by default; noted here because it was
            considered as an accuracy lever during exploration and is a
            reasonable ablation to test explicitly rather than bake in silently.

    Returns:
        A :class:`TranscriptionResult`. Empty-text segments are dropped —
        faster-whisper occasionally emits a zero-length segment at a VAD
        boundary, and an empty segment can never be usefully attributed to a
        speaker or classified by language, so keeping it would only pass a
        no-op through every downstream stage.
    """
    log.info("Transcribing %s", audio_path)
    started = time.perf_counter()

    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=beam_size,
        vad_filter=vad_filter,
        initial_prompt=initial_prompt,
    )

    segments: list[dict[str, Any]] = []
    for segment in segments_iter:
        text = segment.text.strip()
        if not text:
            continue
        segments.append(
            {
                "start": round(segment.start, 2),
                "end": round(segment.end, 2),
                "text": text,
            }
        )

    elapsed = time.perf_counter() - started
    log.info(
        "Transcribed %d segment(s) in %.1fs (detected language: %s, p=%.2f)",
        len(segments),
        elapsed,
        info.language,
        info.language_probability,
    )

    return TranscriptionResult(
        segments=segments,
        detected_language=info.language,
        language_probability=(
            round(info.language_probability, 4) if info.language_probability else None
        ),
        duration_sec=info.duration,
        elapsed_sec=elapsed,
    )
