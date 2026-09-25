"""LLM-based meeting summarization.

Input is expected to be the Hinglish-normalized transcript (falling back to the
tagged, pre-normalization transcript if normalization was skipped — see
:mod:`meeting_assistant.pipeline.stages`, which owns that fallback so every
downstream stage agrees on the same input rather than each guessing
independently).

Output has exactly three keys — ``summary``, ``highlights``,
``key_decisions`` — and the prompt is deliberately strict about not inventing
facts: this stage is judged in the evaluation against a faithfulness rubric,
where hallucinated content is the failure mode that matters most.

A failure here is a **soft** failure, by design: the return type never raises
past ``client.generate_json``'s own errors, and instead reports ``ok=False``
with the error preserved. The batch orchestrator (built in a later phase)
relies on that — an Ollama outage must not discard the transcription and
diarization work that already succeeded, which on a CPU-only setup can be the
most expensive part of a run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from meeting_assistant.errors import LLMError
from meeting_assistant.intel.transcript_text import build_transcript_text
from meeting_assistant.llm.client import OllamaClient
from meeting_assistant.llm.prompts import ACTIVE_SUMMARIZE_PROMPT
from meeting_assistant.logging_setup import get_logger

log = get_logger(__name__)

PromptSpec = tuple[str, str]


@dataclass
class SummaryResult:
    summary: str
    highlights: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    prompt_version: str = ""
    ok: bool = True
    error: str | None = None
    elapsed_sec: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        """The artifact payload written to the ``summary`` artifact."""
        return {
            "summary": self.summary,
            "highlights": self.highlights,
            "key_decisions": self.key_decisions,
        }

    def as_manifest_dict(self) -> dict[str, Any]:
        return {
            "prompt_version": self.prompt_version,
            "ok": self.ok,
            "error": self.error,
            "elapsed_sec": round(self.elapsed_sec, 2),
        }


def summarize_transcript(
    segments: list[dict[str, Any]],
    client: OllamaClient,
    *,
    prompt: PromptSpec = ACTIVE_SUMMARIZE_PROMPT,
) -> SummaryResult:
    """Summarize a transcript with a single LLM call.

    An empty or whitespace-only transcript short-circuits before any LLM call —
    there is nothing to summarize, and sending an empty prompt would only risk
    the model inventing content to fill the response it believes is expected.
    """
    version, system_prompt = prompt
    transcript_text = build_transcript_text(segments)

    if not transcript_text.strip():
        return SummaryResult(summary="", prompt_version=version, ok=True)

    started = time.perf_counter()
    try:
        parsed = client.generate_json(transcript_text, system=system_prompt, expect=dict)
    except LLMError as exc:
        log.warning("Summarization failed: %s", exc)
        return SummaryResult(
            summary="",
            prompt_version=version,
            ok=False,
            error=str(exc),
            elapsed_sec=time.perf_counter() - started,
        )

    elapsed = time.perf_counter() - started
    log.info("Summarized %d segment(s) in %.1fs", len(segments), elapsed)

    return SummaryResult(
        summary=(parsed.get("summary") or "").strip(),
        highlights=[str(h) for h in (parsed.get("highlights") or [])],
        key_decisions=[str(d) for d in (parsed.get("key_decisions") or [])],
        prompt_version=version,
        ok=True,
        elapsed_sec=elapsed,
    )
