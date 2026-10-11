"""Speaker diarization via pyannote.audio: who spoke when.

This module owns one job — timestamped speaker turns — and knows nothing about
what was said. :mod:`meeting_assistant.align.alignment` is what joins this
output with the ASR transcript.

**Import order is load-bearing here.** ``ensure_ffmpeg_dlls()`` must run before
``pyannote.audio`` is imported, because pyannote decodes audio through
TorchCodec, which resolves FFmpeg's DLLs at C-extension load time on Windows.
See :mod:`meeting_assistant.bootstrap.ffmpeg_dll` for the full explanation. The
two lines below are not reorderable, and ``# noqa: E402`` documents that this is
intentional, not an oversight a linter should "fix".
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from meeting_assistant.bootstrap.ffmpeg_dll import ensure_ffmpeg_dlls

ensure_ffmpeg_dlls()  # side effect REQUIRED before the next import

from pyannote.audio import Pipeline  # noqa: E402

from meeting_assistant import config  # noqa: E402
from meeting_assistant.logging_setup import get_logger  # noqa: E402

log = get_logger(__name__)


@dataclass
class DiarizationResult:
    """Speaker turns plus timing, for the manifest."""

    segments: list[dict[str, Any]]
    elapsed_sec: float
    num_speakers_detected: int = field(init=False)

    def __post_init__(self) -> None:
        self.num_speakers_detected = len({s["speaker"] for s in self.segments})

    def as_manifest_dict(self) -> dict[str, Any]:
        return {
            "segments": len(self.segments),
            "speakers_detected": self.num_speakers_detected,
            "elapsed_sec": round(self.elapsed_sec, 2),
        }


def load_pipeline(hf_token: str | None = None, model: str | None = None) -> Pipeline:
    """Load the pretrained diarization pipeline.

    Requires accepting the gated model's terms on Hugging Face for the
    configured ``DIARIZATION_MODEL`` (and its dependency,
    ``pyannote/segmentation-3.0``) — ``meeting-assistant doctor`` names the exact
    repos if access fails.
    """
    hf_token = hf_token if hf_token is not None else config.HF_TOKEN
    model = model or config.DIARIZATION_MODEL

    log.info("Loading diarization pipeline: %s", model)
    started = time.perf_counter()
    pipeline = Pipeline.from_pretrained(model, token=hf_token)
    if config.DIARIZATION_DEVICE != "cpu":
        import torch

        pipeline.to(torch.device(config.DIARIZATION_DEVICE))
        log.info("Diarization pipeline on %s", config.DIARIZATION_DEVICE)
    log.info("Diarization pipeline loaded in %.1fs", time.perf_counter() - started)
    return pipeline


def _unwrap_annotation(result: Any) -> Any:
    """Extract the ``Annotation`` object from a pipeline call's result.

    pyannote.audio 4.x wraps diarization results in a ``DiarizeOutput`` object;
    the annotation itself lives on its ``speaker_diarization`` attribute, and
    calling ``.itertracks()`` on the wrapper directly raises ``AttributeError``.

    The ``getattr`` fallback means a future pyannote version that returns a bare
    ``Annotation`` again degrades gracefully to using it directly, rather than
    breaking. The alternative failure mode — iterating the wrong object entirely
    and silently yielding zero segments — is worse than either case, because an
    all-empty diarization result looks exactly like an audio problem rather than
    an API mismatch.
    """
    return getattr(result, "speaker_diarization", result)


def diarize_audio(
    pipeline: Pipeline,
    audio_path: str | Path,
    *,
    num_speakers: int | None = None,
) -> DiarizationResult:
    """Run diarization and return timestamped speaker turns.

    Args:
        num_speakers: pass when the true speaker count is known (e.g. from the
            meeting's calendar invite or manual input) — this measurably improves
            diarization accuracy over letting the pipeline estimate it. Left
            unset by default since it usually isn't known ahead of time.
    """
    log.info(
        "Diarizing %s%s",
        audio_path,
        f" (num_speakers={num_speakers})" if num_speakers else "",
    )
    started = time.perf_counter()

    if num_speakers is not None:
        result = pipeline(str(audio_path), num_speakers=num_speakers)
    else:
        result = pipeline(str(audio_path))

    annotation = _unwrap_annotation(result)

    segments: list[dict[str, Any]] = [
        {"start": round(turn.start, 2), "end": round(turn.end, 2), "speaker": speaker}
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    ]

    elapsed = time.perf_counter() - started
    detected = len({s["speaker"] for s in segments})
    log.info("Diarized %d turn(s), %d speaker(s), in %.1fs", len(segments), detected, elapsed)

    return DiarizationResult(segments=segments, elapsed_sec=elapsed)
