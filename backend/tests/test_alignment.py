"""Tests for timestamp-overlap speaker attribution."""

from __future__ import annotations

import pytest

from meeting_assistant.align.alignment import (
    UNKNOWN_SPEAKER,
    align_transcript,
    attribution_summary,
    compute_overlap,
    find_best_speaker,
    merge_consecutive_same_speaker,
)


# --------------------------------------------------------------------------
# compute_overlap
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ((0.0, 5.0), (10.0, 15.0), 0.0),      # disjoint, a before b
        ((10.0, 15.0), (0.0, 5.0), 0.0),      # disjoint, b before a
        ((0.0, 5.0), (5.0, 10.0), 0.0),       # touching endpoints are not overlap
        ((0.0, 10.0), (2.0, 4.0), 2.0),       # b nested in a
        ((2.0, 4.0), (0.0, 10.0), 2.0),       # a nested in b
        ((0.0, 5.0), (0.0, 5.0), 5.0),        # identical
        ((0.0, 5.0), (3.0, 8.0), 2.0),        # partial
        ((0.0, 5.0), (2.0, 2.0), 0.0),        # zero-length interval
    ],
)
def test_compute_overlap(a, b, expected):
    assert compute_overlap(a[0], a[1], b[0], b[1]) == pytest.approx(expected)


# --------------------------------------------------------------------------
# find_best_speaker
# --------------------------------------------------------------------------
def test_picks_the_speaker_with_most_overlap():
    segment = {"start": 0.0, "end": 10.0}
    turns = [
        {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
        {"start": 3.0, "end": 10.0, "speaker": "SPEAKER_01"},
    ]
    speaker, ratio = find_best_speaker(segment, turns)
    assert speaker == "SPEAKER_01"
    assert ratio == pytest.approx(0.7)


def test_accumulates_overlap_across_a_speakers_separate_turns():
    """A speaker split across turns must not lose to one contiguous rival.

    Diarization routinely fragments continuous speech, so scoring per-turn rather
    than per-speaker would under-credit whoever got interrupted.
    """
    segment = {"start": 0.0, "end": 10.0}
    turns = [
        {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
        {"start": 3.0, "end": 6.0, "speaker": "SPEAKER_01"},
        {"start": 6.0, "end": 10.0, "speaker": "SPEAKER_00"},
    ]
    speaker, _ = find_best_speaker(segment, turns)
    assert speaker == "SPEAKER_00"  # 7s total, versus SPEAKER_01's 3s


def test_no_overlap_yields_unknown():
    segment = {"start": 0.0, "end": 5.0}
    turns = [{"start": 20.0, "end": 30.0, "speaker": "SPEAKER_00"}]
    assert find_best_speaker(segment, turns) == (UNKNOWN_SPEAKER, 0.0)


def test_empty_speaker_list_yields_unknown():
    assert find_best_speaker({"start": 0.0, "end": 5.0}, []) == (UNKNOWN_SPEAKER, 0.0)


def test_sliver_of_overlap_is_rejected_as_unreliable():
    """A segment sitting in a diarization gap must not be confidently attributed.

    Clipping the edge of a neighbouring turn is precisely the case where the best
    available speaker is most likely to be the wrong one.
    """
    segment = {"start": 0.0, "end": 10.0}
    turns = [{"start": 9.7, "end": 12.0, "speaker": "SPEAKER_00"}]
    speaker, _ = find_best_speaker(segment, turns)
    assert speaker == UNKNOWN_SPEAKER


def test_overlap_threshold_is_configurable():
    segment = {"start": 0.0, "end": 10.0}
    turns = [{"start": 9.7, "end": 12.0, "speaker": "SPEAKER_00"}]
    speaker, _ = find_best_speaker(segment, turns, min_overlap_ratio=0.01)
    assert speaker == "SPEAKER_00"


def test_zero_duration_segment_does_not_divide_by_zero():
    segment = {"start": 5.0, "end": 5.0}
    turns = [{"start": 0.0, "end": 10.0, "speaker": "SPEAKER_00"}]
    speaker, ratio = find_best_speaker(segment, turns)
    # No overlap is possible with a zero-length interval, so this is UNKNOWN.
    assert (speaker, ratio) == (UNKNOWN_SPEAKER, 0.0)


def test_ratio_never_exceeds_one():
    segment = {"start": 2.0, "end": 4.0}
    turns = [{"start": 0.0, "end": 100.0, "speaker": "SPEAKER_00"}]
    _, ratio = find_best_speaker(segment, turns)
    assert ratio == pytest.approx(1.0)


# --------------------------------------------------------------------------
# align_transcript
# --------------------------------------------------------------------------
def test_alignment_preserves_segment_count_and_order(whisper_segments, speaker_segments):
    aligned = align_transcript(whisper_segments, speaker_segments)
    assert len(aligned) == len(whisper_segments)
    assert [s["text"] for s in aligned] == [s["text"] for s in whisper_segments]


def test_alignment_preserves_timestamps_exactly(whisper_segments, speaker_segments):
    """Alignment attributes speech; it must never move it in time."""
    aligned = align_transcript(whisper_segments, speaker_segments)
    for original, result in zip(whisper_segments, aligned, strict=True):
        assert result["start"] == original["start"]
        assert result["end"] == original["end"]


def test_alignment_attaches_speaker_and_confidence(whisper_segments, speaker_segments):
    aligned = align_transcript(whisper_segments, speaker_segments)
    assert aligned[0]["speaker"] == "SPEAKER_00"
    assert aligned[1]["speaker"] == "SPEAKER_01"
    assert all("speaker_overlap" in segment for segment in aligned)


def test_alignment_of_empty_transcript_is_empty():
    assert align_transcript([], [{"start": 0, "end": 1, "speaker": "SPEAKER_00"}]) == []


def test_alignment_does_not_mutate_inputs(whisper_segments, speaker_segments):
    before = [dict(s) for s in whisper_segments]
    align_transcript(whisper_segments, speaker_segments)
    assert whisper_segments == before


# --------------------------------------------------------------------------
# merge_consecutive_same_speaker
# --------------------------------------------------------------------------
def _seg(start, end, speaker, text="x"):
    return {"start": start, "end": end, "speaker": speaker, "text": text}


def test_merges_adjacent_segments_from_one_speaker():
    merged = merge_consecutive_same_speaker(
        [_seg(0, 2, "A", "hello"), _seg(2, 4, "A", "there"), _seg(4, 6, "B", "hi")]
    )
    assert len(merged) == 2
    assert merged[0]["start"] == 0
    assert merged[0]["end"] == 4
    assert merged[0]["text"] == "hello there"
    assert merged[1]["speaker"] == "B"


def test_does_not_merge_across_a_different_speaker():
    merged = merge_consecutive_same_speaker(
        [_seg(0, 2, "A"), _seg(2, 4, "B"), _seg(4, 6, "A")]
    )
    assert [s["speaker"] for s in merged] == ["A", "B", "A"]


def test_does_not_merge_unknown_segments():
    """Two unattributed segments are not known to be the same person.

    Merging them would manufacture one continuous turn from speech that may belong
    to two different speakers -- the confident-but-wrong outcome that the UNKNOWN
    label exists to prevent.
    """
    merged = merge_consecutive_same_speaker(
        [_seg(0, 2, UNKNOWN_SPEAKER), _seg(2, 4, UNKNOWN_SPEAKER)]
    )
    assert len(merged) == 2


def test_does_not_merge_across_a_long_silence():
    """Merging over a gap would inflate the speaker's measured speaking time.

    A merged turn spans first start to last end, and speaking time is computed as
    end minus start, so merging across a 30-second pause credits the speaker with
    those 30 seconds. The previous implementation had no gap limit and did this.
    """
    merged = merge_consecutive_same_speaker([_seg(0, 2, "A"), _seg(32, 34, "A")])
    assert len(merged) == 2
    assert merged[0]["end"] == 2


def test_merges_across_a_short_gap():
    merged = merge_consecutive_same_speaker([_seg(0, 2, "A"), _seg(2.5, 4, "A")])
    assert len(merged) == 1
    assert merged[0]["end"] == 4


def test_max_gap_is_configurable():
    segments = [_seg(0, 2, "A"), _seg(32, 34, "A")]
    assert len(merge_consecutive_same_speaker(segments, max_gap_sec=60)) == 1


def test_merging_preserves_total_speaking_time_within_a_turn():
    """The property that matters downstream: merging must not create duration."""
    segments = [_seg(0, 2, "A"), _seg(2, 4, "A"), _seg(4, 6, "A")]
    merged = merge_consecutive_same_speaker(segments)
    assert merged[0]["end"] - merged[0]["start"] == pytest.approx(6.0)


def test_merge_of_empty_list_is_empty():
    assert merge_consecutive_same_speaker([]) == []


def test_merge_of_single_segment_returns_a_copy():
    original = _seg(0, 2, "A", "only")
    merged = merge_consecutive_same_speaker([original])
    assert merged == [original]
    merged[0]["text"] = "changed"
    assert original["text"] == "only"


def test_merge_does_not_mutate_input():
    segments = [_seg(0, 2, "A", "one"), _seg(2, 4, "A", "two")]
    before = [dict(s) for s in segments]
    merge_consecutive_same_speaker(segments)
    assert segments == before


def test_merged_confidence_is_duration_weighted():
    segments = [
        {"start": 0, "end": 9, "speaker": "A", "text": "a", "speaker_overlap": 1.0},
        {"start": 9, "end": 10, "speaker": "A", "text": "b", "speaker_overlap": 0.0},
    ]
    merged = merge_consecutive_same_speaker(segments)
    # Weighted toward the 9-second segment, not a flat mean of 0.5.
    assert merged[0]["speaker_overlap"] > 0.5


# --------------------------------------------------------------------------
# attribution_summary
# --------------------------------------------------------------------------
def test_attribution_summary_counts_unknowns():
    summary = attribution_summary(
        [
            {"speaker": "A", "speaker_overlap": 1.0},
            {"speaker": UNKNOWN_SPEAKER, "speaker_overlap": 0.0},
            {"speaker": "B", "speaker_overlap": 0.5},
        ]
    )
    assert summary["segments"] == 3
    assert summary["attributed"] == 2
    assert summary["unknown"] == 1
    assert summary["unknown_pct"] == pytest.approx(33.33, abs=0.01)
    assert summary["mean_overlap"] == pytest.approx(0.75)


def test_attribution_summary_of_empty_transcript():
    assert attribution_summary([])["segments"] == 0


def test_attribution_summary_with_all_unknown_does_not_divide_by_zero():
    summary = attribution_summary([{"speaker": UNKNOWN_SPEAKER, "speaker_overlap": 0.0}])
    assert summary["mean_overlap"] == 0.0
    assert summary["unknown_pct"] == 100.0
