"""Descriptive metadata for a meeting.

Fields fall into two kinds, and conflating them was a source of confusion worth
naming explicitly.

Derivable from the transcript: duration, speaker count, languages used, word
count. These are computed here.

Not present in the transcript at all: the meeting's identifier, calendar date and
wall-clock time. Nothing in a transcript records when the meeting happened — that
belongs to the recording context. They are therefore accepted as arguments, and
only fall back to "now" so the function remains usable standalone. Once runs are
stored, the caller passes the real values from the run manifest, where the
recording timestamp actually lives.

``duration_sec`` here is the meeting's wall-clock span — last end minus first
start — which is deliberately *not* the summed speaking time reported by
:mod:`meeting_assistant.analytics.speaker_statistics`. The two differ by silence
and by overlapping speech, and both are meaningful. Expect them to disagree.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from meeting_assistant.align.alignment import UNKNOWN_SPEAKER

# Presented in this order when all are present. Alphabetical ordering would put
# Code-Mixed first, which reads oddly for a project where it is the interesting
# case rather than the default one.
_LANGUAGE_ORDER = ["English", "Hindi", "Code-Mixed"]


def format_duration(seconds: float) -> str:
    """Format seconds as ``HH:MM:SS``."""
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def compute_duration(segments: list[dict[str, Any]]) -> float:
    """Wall-clock span of the transcript, in seconds."""
    if not segments:
        return 0.0
    starts = [segment.get("start", 0.0) for segment in segments]
    ends = [segment.get("end", 0.0) for segment in segments]
    return max(0.0, max(ends) - min(starts))


def compute_num_speakers(segments: list[dict[str, Any]]) -> int:
    """Count distinct speakers, excluding ``UNKNOWN``.

    ``UNKNOWN`` is a marker for failed attribution, not a participant. Counting it
    would report a meeting as having one more attendee than it did whenever any
    speech went unattributed.
    """
    labels = {
        segment.get("speaker")
        for segment in segments
        if segment.get("speaker") and segment.get("speaker") != UNKNOWN_SPEAKER
    }
    return len(labels)


def compute_languages_used(segments: list[dict[str, Any]]) -> list[str]:
    """Distinct language tags present, in a stable presentation order.

    Returns an empty list when no segment carries a ``language`` field — which
    happens when this runs before language tagging. Empty is correct there;
    guessing from the text would duplicate the detector's job and could disagree
    with it.
    """
    seen = {segment.get("language") for segment in segments if segment.get("language")}
    ordered = [language for language in _LANGUAGE_ORDER if language in seen]
    ordered.extend(sorted(seen - set(_LANGUAGE_ORDER)))
    return ordered


def compute_total_word_count(segments: list[dict[str, Any]]) -> int:
    """Sum of whitespace word counts across all segments."""
    return sum(len(segment.get("text", "").split()) for segment in segments)


def generate_meeting_id(when: datetime | None = None) -> str:
    """Build an identifier like ``MTG-20260925-141203``.

    Readable and sortable, which suits a filesystem-first design better than a
    UUID. Not collision-proof; the run id is the authoritative key.
    """
    when = when or datetime.now()
    return f"MTG-{when.strftime('%Y%m%d-%H%M%S')}"


def generate_metadata(
    segments: list[dict[str, Any]],
    *,
    meeting_id: str | None = None,
    date: str | None = None,
    time: str | None = None,
) -> dict[str, Any]:
    """Build the metadata record for a transcript.

    Args:
        segments: transcript segments; ideally language-tagged, so
            ``languages_used`` is populated.
        meeting_id: identifier from the caller. Generated if omitted.
        date: ``YYYY-MM-DD``. Today if omitted.
        time: ``HH:MM:SS``. Now if omitted.
    """
    now = datetime.now()
    duration = compute_duration(segments)

    return {
        "meeting_id": meeting_id or generate_meeting_id(now),
        "date": date or now.strftime("%Y-%m-%d"),
        "time": time or now.strftime("%H:%M:%S"),
        "duration_sec": round(duration, 2),
        "duration_readable": format_duration(duration),
        "num_speakers": compute_num_speakers(segments),
        "languages_used": compute_languages_used(segments),
        "total_word_count": compute_total_word_count(segments),
        "segment_count": len(segments),
    }
