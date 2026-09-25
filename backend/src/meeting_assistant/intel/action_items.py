"""LLM-based action-item extraction.

Shares its transcript formatting with :mod:`meeting_assistant.intel.summarization`
via :mod:`meeting_assistant.intel.transcript_text` rather than importing across
sibling modules — the previous version of this project had this module import a
private, underscore-prefixed helper directly out of the summarization module,
which meant the two could only be kept in sync by whoever remembered the other
existed.

The extraction prompt's hardest rule, and the one most worth restating here: an
**empty** ``action_items`` list is a completely valid, correct result for a
meeting where nothing concrete was assigned. This function must never treat an
empty result as suspicious or as a reason to retry more aggressively than any
other malformed response — a meeting can simply have had no action items, and
forcing the model to find some would be the exact hallucination failure mode the
evaluation is designed to catch.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from meeting_assistant.errors import LLMError
from meeting_assistant.intel.transcript_text import build_transcript_text
from meeting_assistant.llm.client import OllamaClient
from meeting_assistant.llm.prompts import ACTIVE_ACTION_ITEMS_PROMPT
from meeting_assistant.logging_setup import get_logger

log = get_logger(__name__)

PromptSpec = tuple[str, str]


@dataclass
class ActionItemsResult:
    action_items: list[dict[str, Any]] = field(default_factory=list)
    prompt_version: str = ""
    ok: bool = True
    error: str | None = None
    elapsed_sec: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        """The artifact payload written to the ``action_items`` artifact."""
        return {"action_items": self.action_items}

    def as_manifest_dict(self) -> dict[str, Any]:
        return {
            "count": len(self.action_items),
            "prompt_version": self.prompt_version,
            "ok": self.ok,
            "error": self.error,
            "elapsed_sec": round(self.elapsed_sec, 2),
        }


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    """Guarantee all four keys are present, so downstream code (the API,
    the UI, an export) can always rely on their presence rather than
    special-casing whichever ones the model happened to omit.
    """
    return {
        "person": item.get("person") or None,
        "task": str(item.get("task") or "").strip(),
        "deadline": item.get("deadline") or None,
        "status": item.get("status") or None,
    }


def extract_action_items(
    segments: list[dict[str, Any]],
    client: OllamaClient,
    *,
    prompt: PromptSpec = ACTIVE_ACTION_ITEMS_PROMPT,
) -> ActionItemsResult:
    """Extract concrete action items from a transcript with one LLM call."""
    version, system_prompt = prompt
    transcript_text = build_transcript_text(segments)

    if not transcript_text.strip():
        return ActionItemsResult(prompt_version=version, ok=True)

    started = time.perf_counter()
    try:
        parsed = client.generate_json(transcript_text, system=system_prompt, expect=dict)
    except LLMError as exc:
        log.warning("Action item extraction failed: %s", exc)
        return ActionItemsResult(
            prompt_version=version,
            ok=False,
            error=str(exc),
            elapsed_sec=time.perf_counter() - started,
        )

    raw_items = parsed.get("action_items") or []
    items = [_normalize_item(item) for item in raw_items if isinstance(item, dict)]
    # An item with no task text is junk the model emitted despite instructions,
    # not a real (if sparse) result -- dropped rather than kept as a blank row.
    items = [item for item in items if item["task"]]

    elapsed = time.perf_counter() - started
    log.info("Extracted %d action item(s) in %.1fs", len(items), elapsed)

    return ActionItemsResult(
        action_items=items,
        prompt_version=version,
        ok=True,
        elapsed_sec=elapsed,
    )
