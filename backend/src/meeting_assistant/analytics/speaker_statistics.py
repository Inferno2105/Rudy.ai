"""Per-speaker participation statistics.

Pure arithmetic over a speaker-attributed transcript: no model, no LLM, fully
deterministic.

Two definitions worth stating, because both are choices rather than the only
possible reading:

*Speaking time* is the sum of a speaker's segment durations, not wall-clock span.
Silence between turns belongs to nobody. If two speakers genuinely overlap, each
is credited the full duration of their own segments — apportioning shared seconds
between simultaneous speakers is out of scope, and the consequence is that total
speaking time can exceed meeting duration when people talk over each other.
That is reported rather than hidden, since it is itself a meaningful signal about
a meeting.

*Participation share* is a fraction of total speaking time, not of meeting
duration. Otherwise a meeting with long silences would show everyone
participating little, which describes the recording rather than the people.

Unattributed speech (``UNKNOWN``) is counted and reported separately rather than
being dropped or treated as a participant. Dropping it would inflate everyone
else's share; treating it as a speaker would invent one.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from meeting_assistant.align.alignment import UNKNOWN_SPEAKER


def count_words(text: str) -> int:
    """Whitespace word count.

    Deliberately naive, and consistent with how the language detector tokenizes,
    so the two never disagree about how many words a segment holds. A
    morphological tokenizer would be more accurate for Hindi but would make word
    counts incomparable across the pipeline.
    """
    return len(text.split())


def compute_speaker_statistics(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute per-speaker statistics and meeting-level totals.

    Returns:
        ``{"speakers": {label: {...}}, "totals": {...}}``.

        The nesting is a change from the previous flat mapping of label to stats.
        A flat dict left nowhere to put meeting-level figures without a key that
        could collide with a speaker label, and the totals are what make the
        per-speaker numbers interpretable — particularly unattributed time, which
        is the caveat on every share below it.
    """
    speaking_time: dict[str, float] = defaultdict(float)
    utterances: dict[str, int] = defaultdict(int)
    words: dict[str, int] = defaultdict(int)

    for segment in segments:
        label = segment.get("speaker") or UNKNOWN_SPEAKER
        duration = max(0.0, segment.get("end", 0.0) - segment.get("start", 0.0))
        speaking_time[label] += duration
        utterances[label] += 1
        words[label] += count_words(segment.get("text", ""))

    # Shares are over attributed speech only. Including unattributed time in the
    # denominator would make every speaker's share depend on how well diarization
    # happened to perform, which is a different measurement.
    attributed_time = sum(
        seconds for label, seconds in speaking_time.items() if label != UNKNOWN_SPEAKER
    )

    speakers: dict[str, dict[str, Any]] = {}
    for label in sorted(speaking_time):
        if label == UNKNOWN_SPEAKER:
            continue
        seconds = speaking_time[label]
        speakers[label] = {
            "speaking_time_sec": round(seconds, 2),
            "participation_pct": (
                round(100.0 * seconds / attributed_time, 2) if attributed_time > 0 else 0.0
            ),
            "utterance_count": utterances[label],
            "word_count": words[label],
            "words_per_minute": (
                round(words[label] / (seconds / 60.0), 1) if seconds > 0 else 0.0
            ),
            "mean_utterance_sec": (
                round(seconds / utterances[label], 2) if utterances[label] else 0.0
            ),
        }

    unattributed_time = round(speaking_time.get(UNKNOWN_SPEAKER, 0.0), 2)
    total_time = round(attributed_time + unattributed_time, 2)

    return {
        "speakers": speakers,
        "totals": {
            "num_speakers": len(speakers),
            "attributed_time_sec": round(attributed_time, 2),
            "unattributed_time_sec": unattributed_time,
            "unattributed_pct": (
                round(100.0 * unattributed_time / total_time, 2) if total_time > 0 else 0.0
            ),
            "total_speaking_time_sec": total_time,
            "utterance_count": sum(utterances.values()),
            "word_count": sum(words.values()),
        },
    }


def most_active_speaker(stats: dict[str, Any]) -> str | None:
    """Label of the speaker with the most speaking time, or ``None``."""
    speakers = stats.get("speakers") or {}
    if not speakers:
        return None
    return max(speakers, key=lambda label: speakers[label]["speaking_time_sec"])
