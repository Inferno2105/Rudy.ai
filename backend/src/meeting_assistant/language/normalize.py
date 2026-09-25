"""Hinglish normalization: rewrite Devanagari transcript text into Roman script.

**Problem this solves.** faster-whisper's Hindi mode outputs pure Devanagari,
and even forces English words spoken mid-sentence into Devanagari phonetics
(e.g. "test" -> "टेष्ट"). This stage rewrites that into Hinglish/Roman script:
Hindi spelled phonetically in Roman letters, genuine English left as English,
meaning unchanged. It is a script-conversion pass, not translation — the model
is instructed not to alter word order or meaning, only spelling.

**Ordering constraint.** This must run *after*
:mod:`meeting_assistant.language.detection` and never before it. The detector
classifies segments by comparing Devanagari against Latin script, and this
stage's entire job is to erase that distinction by rewriting Devanagari into
Latin. Run in the wrong order, nothing raises an error — every segment is
simply mislabeled English afterward. The pipeline's stage dependencies (see
:mod:`meeting_assistant.paths`) enforce this so it cannot happen by accident;
this module does its part by never touching the ``language`` field a segment
already carries.

**Known, deliberate limitation.** Normalization must not and cannot fix genuine
ASR transcription errors — a mis-heard word stays mis-heard, faithfully
transliterated. That is a source-accuracy problem belonging to the ASR stage,
not a script-conversion problem; conflating the two would make it impossible to
tell, from a wrong-looking segment, which stage actually failed.

**Cost.** One LLM call per segment. On a CPU this is the pipeline's slowest
stage per unit of transcript length by a wide margin, and it is deliberately
left that way here rather than silently batched — the tradeoff between
per-segment and batched calls is a real design decision with a quality
implication (a batched call has to reconstruct segment boundaries from the
model's response, which is not free), so it is treated as a measured
evaluation ablation rather than an unstated choice.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from meeting_assistant.errors import LLMError
from meeting_assistant.llm.client import OllamaClient
from meeting_assistant.llm.prompts import ACTIVE_NORMALIZE_PROMPT
from meeting_assistant.logging_setup import get_logger

log = get_logger(__name__)

PromptSpec = tuple[str, str]


@dataclass
class NormalizationResult:
    """Normalized segments plus a record of how well the pass went."""

    segments: list[dict[str, Any]]
    prompt_version: str
    failed_segments: int
    elapsed_sec: float

    def as_manifest_dict(self) -> dict[str, Any]:
        return {
            "segments": len(self.segments),
            "prompt_version": self.prompt_version,
            "failed_segments": self.failed_segments,
            "elapsed_sec": round(self.elapsed_sec, 2),
        }


def normalize_text(
    text: str,
    client: OllamaClient,
    *,
    prompt: PromptSpec = ACTIVE_NORMALIZE_PROMPT,
) -> tuple[str, bool]:
    """Convert one segment's text to Hinglish/Roman script.

    Returns:
        ``(text, ok)``. On failure, ``text`` is the **original** input
        unchanged and ``ok`` is ``False`` — one bad segment must never corrupt
        the transcript or abort the run, but the caller still needs to know a
        failure happened rather than have it disappear silently into an
        unmodified segment that looks identical to a genuinely-unchanged one.
    """
    _version, system_prompt = prompt
    try:
        result = client.generate(text, system=system_prompt)
    except LLMError as exc:
        log.warning("Normalization failed for a segment, keeping original: %s", exc)
        return text, False
    return (result if result else text), True


def normalize_transcript(
    segments: list[dict[str, Any]],
    client: OllamaClient,
    *,
    prompt: PromptSpec = ACTIVE_NORMALIZE_PROMPT,
) -> NormalizationResult:
    """Normalize every segment's ``text`` field.

    Only ``text`` changes. ``start``, ``end``, ``speaker`` and — critically —
    any existing ``language`` tag pass through completely untouched, so the
    tagging stage's output remains valid after this stage runs.
    """
    version, _ = prompt
    started = time.perf_counter()

    normalized: list[dict[str, Any]] = []
    failed = 0
    total = len(segments)

    for index, segment in enumerate(segments, start=1):
        text, ok = normalize_text(segment.get("text", ""), client, prompt=prompt)
        new_segment = dict(segment)
        new_segment["text"] = text
        normalized.append(new_segment)
        if not ok:
            failed += 1
        log.debug("Normalized segment %d/%d", index, total)

    elapsed = time.perf_counter() - started
    log.info("Normalized %d segment(s) in %.1fs (%d failed)", total, elapsed, failed)

    return NormalizationResult(
        segments=normalized,
        prompt_version=version,
        failed_segments=failed,
        elapsed_sec=elapsed,
    )
