"""Assemble per-chunk results into one continuous meeting transcript.

Live capture cuts audio at natural pauses, and each chunk is transcribed and
diarized as a standalone file starting at its own time zero. Building one
transcript means shifting every chunk's timestamps forward by where that chunk
began in the recording.

Speaker labels are the harder half. Diarization has no memory between chunks, so
``SPEAKER_00`` in chunk two is not known to be the same person as ``SPEAKER_00``
in chunk one — the labels are chunk-local. Two mechanisms address this, and they
are mutually exclusive by design:

*Voice-embedding resolution* (:mod:`meeting_assistant.diarize.speaker_registry`)
compares voices across chunks and assigns stable global labels. When it succeeds,
segments arrive marked ``speaker_resolution="global"`` and are stitched unchanged.

*Chunk prefixing* rewrites a label as ``C2_SPEAKER_00``, making the ambiguity
visible rather than implying continuity the data does not support. This applies
only to segments the registry did not resolve.

Why exclusive rather than layered: an earlier design prefixed every label and then
let the registry overwrite the result. That leaves a window in which each segment
holds a value nobody intends to keep, and any artifact written from that
intermediate state carries labels that are wrong in a way nothing flags. It also
inverts the cost of the two mechanisms — a prefixed label is a *correct* statement
of uncertainty, but applied to a resolved segment it fragments one speaker into
``C1_SPEAKER_00``, ``C2_SPEAKER_00``, ``C3_SPEAKER_00``, which inflates the
speaker count and splits one person's participation share three ways. So the
prefix appears exactly when identity is genuinely unknown, and never otherwise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from meeting_assistant.align.alignment import UNKNOWN_SPEAKER
from meeting_assistant.io_utils import write_json

# Set on a segment by the speaker registry to record how its label was decided.
RESOLUTION_GLOBAL = "global"
RESOLUTION_UNRESOLVED = "unresolved"


def _needs_prefix(segment: dict[str, Any]) -> bool:
    """Whether this segment's label is chunk-local and should be marked as such."""
    if segment.get("speaker_resolution") == RESOLUTION_GLOBAL:
        return False
    label = segment.get("speaker")
    # UNKNOWN is already a statement of uncertainty; prefixing it would only
    # produce C2_UNKNOWN, which says nothing more and breaks grouping downstream.
    return bool(label) and label != UNKNOWN_SPEAKER


def offset_segments(
    segments: list[dict[str, Any]],
    offset_sec: float,
    chunk_index: int,
    *,
    prefix_speakers: bool = True,
) -> list[dict[str, Any]]:
    """Shift segments onto the meeting timeline, prefixing unresolved labels.

    Args:
        segments: one chunk's aligned segments, timed from that chunk's zero.
        offset_sec: where the chunk began in the recording.
        chunk_index: 1-based, used for the prefix and recorded on each segment.
        prefix_speakers: when ``False``, labels are left alone regardless of
            resolution state. Used when identity is handled entirely elsewhere.

    Returns a new list; the inputs are not modified.
    """
    shifted: list[dict[str, Any]] = []

    for segment in segments:
        new_segment = dict(segment)
        new_segment["start"] = round(segment.get("start", 0.0) + offset_sec, 2)
        new_segment["end"] = round(segment.get("end", 0.0) + offset_sec, 2)
        new_segment["chunk"] = chunk_index

        if prefix_speakers and _needs_prefix(segment):
            new_segment["local_speaker"] = segment["speaker"]
            new_segment["speaker"] = f"C{chunk_index}_{segment['speaker']}"
            new_segment["speaker_resolution"] = RESOLUTION_UNRESOLVED

        shifted.append(new_segment)

    return shifted


class TranscriptStitcher:
    """Accumulates chunk results into one transcript.

    Exposes the running transcript at any point, so the live pipeline can write a
    valid partial artifact after every chunk rather than only at the end. That
    matters because the alternative — holding everything in memory until the user
    stops recording — loses the whole meeting if the process dies.
    """

    def __init__(self) -> None:
        self.all_segments: list[dict[str, Any]] = []
        self.chunk_count = 0

    def add_chunk(
        self,
        aligned_segments: list[dict[str, Any]],
        offset_sec: float,
        *,
        prefix_speakers: bool = True,
    ) -> list[dict[str, Any]]:
        """Shift and append one chunk's segments. Returns just that chunk's."""
        self.chunk_count += 1
        shifted = offset_segments(
            aligned_segments,
            offset_sec,
            self.chunk_count,
            prefix_speakers=prefix_speakers,
        )
        self.all_segments.extend(shifted)
        return shifted

    def get_full_transcript(self) -> list[dict[str, Any]]:
        """The whole transcript, sorted by start time.

        Chunks are processed in order, so the sort is defensive rather than
        necessary — but a single out-of-order segment would corrupt every
        downstream duration calculation, and sorting is cheap.
        """
        return sorted(self.all_segments, key=lambda segment: segment.get("start", 0.0))

    def save(self, path: str | Path) -> Path:
        """Write the transcript to ``path``.

        ``path`` is required. The previous version defaulted to a shared location,
        which is how successive runs came to overwrite each other's transcripts;
        there is deliberately no default to fall back on.
        """
        return write_json(path, self.get_full_transcript())

    def summary(self) -> dict[str, Any]:
        """Counts for the run manifest."""
        segments = self.all_segments
        labels = {
            segment.get("speaker")
            for segment in segments
            if segment.get("speaker") and segment.get("speaker") != UNKNOWN_SPEAKER
        }
        unresolved = sum(
            1 for s in segments if s.get("speaker_resolution") == RESOLUTION_UNRESOLVED
        )
        return {
            "chunks": self.chunk_count,
            "segments": len(segments),
            "distinct_speaker_labels": len(labels),
            "unresolved_segments": unresolved,
        }
