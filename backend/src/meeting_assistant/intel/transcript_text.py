"""Flatten a speaker-attributed transcript into plain text for LLM prompts.

Shared by every stage that sends the whole transcript to a model —
summarization and action-item extraction — so both read the same format and
never drift apart. The previous version of this project had action-item
extraction import this function from inside the summarization module, which
meant the two could only be kept consistent by accident; it now lives
independently of either consumer.
"""

from __future__ import annotations

from typing import Any


def format_timestamp(seconds: float) -> str:
    """Render seconds as ``MM:SS``, for readability inside a prompt."""
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def build_transcript_text(segments: list[dict[str, Any]]) -> str:
    """Flatten segments into ``[MM:SS] SPEAKER: text`` lines.

    Timestamps are included so the model has a sense of the meeting's pacing
    without the caller having to compute duration or structure separately.
    Segments with empty text are skipped — an LLM call gains nothing from a
    blank line, and it would only cost prompt tokens.
    """
    lines: list[str] = []
    for segment in segments:
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        timestamp = format_timestamp(segment.get("start", 0.0))
        speaker = segment.get("speaker") or "UNKNOWN"
        lines.append(f"[{timestamp}] {speaker}: {text}")
    return "\n".join(lines)
