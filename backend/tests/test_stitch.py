"""Tests for assembling per-chunk results into one transcript.

The prefix tests carry most of the weight here. Chunk prefixing and global
speaker-identity resolution must be mutually exclusive: applying a ``C2_`` prefix
to a segment whose speaker has been genuinely identified fragments one person
into several labels, which inflates the speaker count and splits their
participation share. Applying it when identity really is unknown is correct and
necessary. These tests pin that distinction.
"""

from __future__ import annotations

import pytest

from meeting_assistant.align.alignment import UNKNOWN_SPEAKER
from meeting_assistant.align.stitch import (
    RESOLUTION_GLOBAL,
    RESOLUTION_UNRESOLVED,
    TranscriptStitcher,
    offset_segments,
)
from meeting_assistant.io_utils import read_json


def _seg(start, end, speaker="SPEAKER_00", text="hello", **extra):
    return {"start": start, "end": end, "speaker": speaker, "text": text, **extra}


# --------------------------------------------------------------------------
# offset_segments — timestamps
# --------------------------------------------------------------------------
def test_shifts_both_bounds_onto_the_meeting_timeline():
    shifted = offset_segments([_seg(1.0, 3.0)], offset_sec=10.0, chunk_index=1)
    assert shifted[0]["start"] == 11.0
    assert shifted[0]["end"] == 13.0


def test_rounds_to_two_decimal_places():
    shifted = offset_segments([_seg(1.0, 3.0)], offset_sec=0.123456, chunk_index=1)
    assert shifted[0]["start"] == 1.12
    assert shifted[0]["end"] == 3.12


def test_zero_offset_leaves_timestamps_unchanged():
    shifted = offset_segments([_seg(1.5, 3.25)], offset_sec=0.0, chunk_index=1)
    assert (shifted[0]["start"], shifted[0]["end"]) == (1.5, 3.25)


def test_records_the_chunk_index_on_each_segment():
    shifted = offset_segments([_seg(0, 1)], offset_sec=0.0, chunk_index=7)
    assert shifted[0]["chunk"] == 7


def test_preserves_unrelated_fields():
    shifted = offset_segments(
        [_seg(0, 1, language="Hindi", speaker_overlap=0.9)], offset_sec=5.0, chunk_index=1
    )
    assert shifted[0]["language"] == "Hindi"
    assert shifted[0]["speaker_overlap"] == 0.9
    assert shifted[0]["text"] == "hello"


def test_does_not_mutate_input():
    segments = [_seg(1.0, 3.0)]
    before = [dict(s) for s in segments]
    offset_segments(segments, offset_sec=10.0, chunk_index=1)
    assert segments == before


def test_empty_input_gives_empty_output():
    assert offset_segments([], offset_sec=5.0, chunk_index=1) == []


# --------------------------------------------------------------------------
# offset_segments — speaker labels
# --------------------------------------------------------------------------
def test_prefixes_an_unresolved_chunk_local_label():
    shifted = offset_segments([_seg(0, 1, "SPEAKER_00")], offset_sec=0.0, chunk_index=3)
    assert shifted[0]["speaker"] == "C3_SPEAKER_00"
    assert shifted[0]["local_speaker"] == "SPEAKER_00"
    assert shifted[0]["speaker_resolution"] == RESOLUTION_UNRESOLVED


def test_does_not_prefix_a_globally_resolved_label():
    """The key exclusion.

    Prefixing a resolved speaker would split one person across chunks, inflating
    the speaker count and dividing their participation share.
    """
    segment = _seg(0, 1, "SPEAKER_00", speaker_resolution=RESOLUTION_GLOBAL)
    shifted = offset_segments([segment], offset_sec=0.0, chunk_index=3)
    assert shifted[0]["speaker"] == "SPEAKER_00"
    assert shifted[0]["speaker_resolution"] == RESOLUTION_GLOBAL


def test_does_not_prefix_unknown():
    """UNKNOWN already states uncertainty; C2_UNKNOWN adds nothing and breaks grouping."""
    shifted = offset_segments([_seg(0, 1, UNKNOWN_SPEAKER)], offset_sec=0.0, chunk_index=2)
    assert shifted[0]["speaker"] == UNKNOWN_SPEAKER


def test_does_not_prefix_a_missing_or_empty_label():
    shifted = offset_segments(
        [{"start": 0, "end": 1, "text": "x"}, _seg(0, 1, "")], offset_sec=0.0, chunk_index=2
    )
    assert "speaker" not in shifted[0] or shifted[0].get("speaker") in (None, "")
    assert shifted[1]["speaker"] == ""


def test_prefixing_can_be_disabled_entirely():
    shifted = offset_segments(
        [_seg(0, 1, "SPEAKER_00")], offset_sec=0.0, chunk_index=3, prefix_speakers=False
    )
    assert shifted[0]["speaker"] == "SPEAKER_00"
    assert "local_speaker" not in shifted[0]


def test_a_segment_is_never_both_prefixed_and_marked_global():
    """The invariant, stated directly."""
    mixed = [
        _seg(0, 1, "SPEAKER_00"),
        _seg(1, 2, "SPEAKER_01", speaker_resolution=RESOLUTION_GLOBAL),
    ]
    shifted = offset_segments(mixed, offset_sec=0.0, chunk_index=2)
    for segment in shifted:
        prefixed = segment["speaker"].startswith("C2_")
        is_global = segment.get("speaker_resolution") == RESOLUTION_GLOBAL
        assert not (prefixed and is_global)


# --------------------------------------------------------------------------
# TranscriptStitcher
# --------------------------------------------------------------------------
def test_chunk_count_increments_and_drives_the_prefix():
    stitcher = TranscriptStitcher()
    first = stitcher.add_chunk([_seg(0, 1, "SPEAKER_00")], offset_sec=0.0)
    second = stitcher.add_chunk([_seg(0, 1, "SPEAKER_00")], offset_sec=10.0)
    assert stitcher.chunk_count == 2
    assert first[0]["speaker"] == "C1_SPEAKER_00"
    assert second[0]["speaker"] == "C2_SPEAKER_00"


def test_add_chunk_returns_only_that_chunks_segments():
    """The live pipeline prints each chunk as it arrives, not the whole transcript."""
    stitcher = TranscriptStitcher()
    stitcher.add_chunk([_seg(0, 1)], offset_sec=0.0)
    returned = stitcher.add_chunk([_seg(0, 1), _seg(1, 2)], offset_sec=10.0)
    assert len(returned) == 2
    assert len(stitcher.all_segments) == 3


def test_full_transcript_is_sorted_by_start_time():
    """Defensive: one out-of-order segment would corrupt every duration downstream."""
    stitcher = TranscriptStitcher()
    stitcher.add_chunk([_seg(0, 1)], offset_sec=100.0)
    stitcher.add_chunk([_seg(0, 1)], offset_sec=0.0)
    starts = [s["start"] for s in stitcher.get_full_transcript()]
    assert starts == sorted(starts)


def test_save_requires_an_explicit_path(tmp_path):
    """No default output location exists to fall back on, by design."""
    stitcher = TranscriptStitcher()
    with pytest.raises(TypeError):
        stitcher.save()  # type: ignore[call-arg]


def test_save_writes_the_sorted_transcript(tmp_path):
    stitcher = TranscriptStitcher()
    stitcher.add_chunk([_seg(0, 1, text="second")], offset_sec=50.0)
    stitcher.add_chunk([_seg(0, 1, text="first")], offset_sec=0.0)

    target = tmp_path / "merged.json"
    stitcher.save(target)

    saved = read_json(target)
    assert [s["text"] for s in saved] == ["first", "second"]


def test_save_can_be_called_repeatedly_for_incremental_dumps(tmp_path):
    """The live pipeline re-dumps after every chunk so a kill leaves valid output."""
    stitcher = TranscriptStitcher()
    target = tmp_path / "merged.json"

    stitcher.add_chunk([_seg(0, 1)], offset_sec=0.0)
    stitcher.save(target)
    assert len(read_json(target)) == 1

    stitcher.add_chunk([_seg(0, 1)], offset_sec=10.0)
    stitcher.save(target)
    assert len(read_json(target)) == 2


def test_empty_stitcher_saves_an_empty_list(tmp_path):
    target = tmp_path / "merged.json"
    TranscriptStitcher().save(target)
    assert read_json(target) == []


def test_summary_counts_chunks_segments_and_unresolved():
    stitcher = TranscriptStitcher()
    stitcher.add_chunk([_seg(0, 1, "SPEAKER_00")], offset_sec=0.0)
    stitcher.add_chunk(
        [_seg(0, 1, "SPEAKER_00", speaker_resolution=RESOLUTION_GLOBAL)], offset_sec=10.0
    )

    summary = stitcher.summary()
    assert summary["chunks"] == 2
    assert summary["segments"] == 2
    assert summary["unresolved_segments"] == 1
    # C1_SPEAKER_00 and the resolved SPEAKER_00 are distinct labels, which is the
    # fragmentation the registry exists to remove.
    assert summary["distinct_speaker_labels"] == 2


def test_resolved_chunks_do_not_fragment_a_speaker_across_chunks():
    """With resolution in place, one person keeps one label throughout."""
    stitcher = TranscriptStitcher()
    for offset in (0.0, 10.0, 20.0):
        stitcher.add_chunk(
            [_seg(0, 1, "SPEAKER_00", speaker_resolution=RESOLUTION_GLOBAL)],
            offset_sec=offset,
        )
    assert stitcher.summary()["distinct_speaker_labels"] == 1
