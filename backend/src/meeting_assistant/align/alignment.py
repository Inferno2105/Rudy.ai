"""Attribute transcribed text to speakers by timestamp overlap.

The ASR and diarization stages run independently and know nothing about each
other: one produces text spans, the other speaker turns, both as start/end times
over the same audio. This module joins them.

It works purely on timestamps and never inspects the text. That is a deliberate
constraint rather than a simplification — a content-based heuristic would have to
model who says what, which for Hindi-English code-mixed speech means encoding
assumptions about language use per speaker. Those assumptions would be wrong
often, would be impossible to defend in a write-up, and would make attribution
errors correlate with language, contaminating the very thing this project
measures. Overlap arithmetic is explainable and language-agnostic.

Unattributed text is labelled ``UNKNOWN`` rather than assigned to the nearest
speaker. A visible gap is honest and measurable; a confident guess is neither.
"""

from __future__ import annotations

from typing import Any

UNKNOWN_SPEAKER = "UNKNOWN"

# Below this fraction of a text segment covered by a speaker turn, attribution is
# treated as unreliable and the segment is left UNKNOWN. A tiny sliver of overlap
# usually means the segment sits in a diarization gap and merely clips the edge of
# a neighbouring turn, which is exactly the case where picking the best available
# speaker is most likely to be wrong.
MIN_OVERLAP_RATIO = 0.10


def compute_overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Seconds of intersection between two intervals; ``0.0`` if disjoint."""
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def find_best_speaker(
    segment: dict[str, Any],
    speaker_segments: list[dict[str, Any]],
    *,
    min_overlap_ratio: float = MIN_OVERLAP_RATIO,
) -> tuple[str, float]:
    """Find the speaker whose turns overlap ``segment`` most.

    Returns:
        ``(speaker, ratio)`` where ``ratio`` is the fraction of the text
        segment's duration covered by that speaker. The ratio is returned, not
        just used internally, because it is the natural per-segment confidence
        for this join: a transcript where most segments were attributed at 0.9
        is a different result from one where most sat at 0.3, and reporting the
        distribution is more informative than reporting an attribution rate.

        ``(UNKNOWN, 0.0)`` when nothing overlaps, or when the best overlap is
        below ``min_overlap_ratio``.
    """
    duration = max(0.0, segment["end"] - segment["start"])

    best_speaker = UNKNOWN_SPEAKER
    best_overlap = 0.0

    # Accumulate per speaker rather than per turn: diarization often splits one
    # person's continuous speech into several turns, and taking the single
    # largest turn would under-credit a speaker who was interrupted.
    totals: dict[str, float] = {}
    for turn in speaker_segments:
        overlap = compute_overlap(
            segment["start"], segment["end"], turn["start"], turn["end"]
        )
        if overlap > 0:
            label = turn["speaker"]
            totals[label] = totals.get(label, 0.0) + overlap

    for label, overlap in totals.items():
        if overlap > best_overlap:
            best_overlap, best_speaker = overlap, label

    if best_speaker == UNKNOWN_SPEAKER:
        return UNKNOWN_SPEAKER, 0.0

    # A zero-duration segment can't be covered proportionally; any overlap at all
    # is as good as it gets.
    ratio = (best_overlap / duration) if duration > 0 else 1.0
    if ratio < min_overlap_ratio:
        return UNKNOWN_SPEAKER, round(ratio, 4)

    return best_speaker, round(min(ratio, 1.0), 4)


def align_transcript(
    transcript_segments: list[dict[str, Any]],
    speaker_segments: list[dict[str, Any]],
    *,
    min_overlap_ratio: float = MIN_OVERLAP_RATIO,
) -> list[dict[str, Any]]:
    """Attach a speaker to every transcript segment.

    Iterates the transcript rather than the speaker turns, because text
    granularity is what ends up being read. Output segment count always equals
    input segment count — no text is dropped, merged or duplicated here.
    """
    aligned: list[dict[str, Any]] = []
    for segment in transcript_segments:
        speaker, ratio = find_best_speaker(
            segment, speaker_segments, min_overlap_ratio=min_overlap_ratio
        )
        aligned.append(
            {
                "start": segment["start"],
                "end": segment["end"],
                "speaker": speaker,
                "text": segment["text"],
                "speaker_overlap": ratio,
            }
        )
    return aligned


def merge_consecutive_same_speaker(
    aligned: list[dict[str, Any]],
    *,
    max_gap_sec: float = 2.0,
) -> list[dict[str, Any]]:
    """Join adjacent segments from one speaker into a single turn.

    Whisper splits continuous speech into short segments, so an unmerged
    transcript reads as a dump rather than a conversation.

    Two things this deliberately refuses to merge:

    ``UNKNOWN`` segments. Two consecutive unattributed segments are not known to
    be the same person — that is what unattributed means. Merging them would
    manufacture a single continuous turn out of speech that may belong to two
    different speakers, which is the same confident-but-wrong failure the
    ``UNKNOWN`` label exists to avoid.

    Segments separated by more than ``max_gap_sec``. A merged turn spans from its
    first start to its last end, so merging across a long silence silently
    absorbs that silence into the turn's duration. Speaking time is computed as
    ``end - start`` downstream, which means merging a speaker's remarks either
    side of a thirty-second pause would inflate their measured speaking time and
    their participation share by the length of the pause. The previous
    implementation had no gap limit and did exactly that.
    """
    if not aligned:
        return []

    merged: list[dict[str, Any]] = [dict(aligned[0])]

    for segment in aligned[1:]:
        previous = merged[-1]
        gap = segment["start"] - previous["end"]

        mergeable = (
            segment["speaker"] == previous["speaker"]
            and segment["speaker"] != UNKNOWN_SPEAKER
            and gap <= max_gap_sec
        )

        if mergeable:
            previous["end"] = segment["end"]
            previous["text"] = f"{previous['text']} {segment['text']}".strip()
            # Duration-weighted, so the merged confidence reflects the whole turn
            # rather than whichever fragment happened to come last.
            if "speaker_overlap" in previous and "speaker_overlap" in segment:
                previous["speaker_overlap"] = round(
                    _weighted_mean(
                        previous["speaker_overlap"],
                        previous["end"] - previous["start"],
                        segment["speaker_overlap"],
                        segment["end"] - segment["start"],
                    ),
                    4,
                )
        else:
            merged.append(dict(segment))

    return merged


def _weighted_mean(a: float, weight_a: float, b: float, weight_b: float) -> float:
    total = weight_a + weight_b
    if total <= 0:
        return (a + b) / 2
    return (a * weight_a + b * weight_b) / total


def attribution_summary(aligned: list[dict[str, Any]]) -> dict[str, Any]:
    """Report how well attribution went, for the run manifest.

    Surfacing this per run means a transcript whose speaker labels are mostly
    guesswork is visible immediately, rather than being discovered later when the
    speaker statistics look implausible.
    """
    total = len(aligned)
    if total == 0:
        return {"segments": 0, "attributed": 0, "unknown": 0, "mean_overlap": 0.0}

    unknown = sum(1 for s in aligned if s.get("speaker") == UNKNOWN_SPEAKER)
    overlaps = [
        s.get("speaker_overlap", 0.0)
        for s in aligned
        if s.get("speaker") != UNKNOWN_SPEAKER
    ]

    return {
        "segments": total,
        "attributed": total - unknown,
        "unknown": unknown,
        "unknown_pct": round(100.0 * unknown / total, 2),
        "mean_overlap": round(sum(overlaps) / len(overlaps), 4) if overlaps else 0.0,
    }
