"""Tests for speaker statistics and meeting metadata."""

from __future__ import annotations

import pytest

from meeting_assistant.align.alignment import UNKNOWN_SPEAKER
from meeting_assistant.analytics.meeting_metadata import (
    compute_duration,
    compute_languages_used,
    compute_num_speakers,
    compute_total_word_count,
    format_duration,
    generate_meeting_id,
    generate_metadata,
)
from meeting_assistant.analytics.speaker_statistics import (
    compute_speaker_statistics,
    count_words,
    most_active_speaker,
)


def _seg(start, end, speaker, text="one two three"):
    return {"start": start, "end": end, "speaker": speaker, "text": text}


# ==========================================================================
# Speaker statistics
# ==========================================================================
def test_participation_shares_sum_to_one_hundred():
    stats = compute_speaker_statistics(
        [_seg(0, 10, "A"), _seg(10, 20, "B"), _seg(20, 25, "C")]
    )
    total = sum(s["participation_pct"] for s in stats["speakers"].values())
    assert total == pytest.approx(100.0, abs=0.05)


def test_single_speaker_has_full_participation():
    stats = compute_speaker_statistics([_seg(0, 10, "A")])
    assert stats["speakers"]["A"]["participation_pct"] == pytest.approx(100.0)


def test_speaking_time_sums_segment_durations_not_wall_clock_span():
    """Silence between turns belongs to nobody."""
    stats = compute_speaker_statistics([_seg(0, 5, "A"), _seg(55, 60, "A")])
    assert stats["speakers"]["A"]["speaking_time_sec"] == pytest.approx(10.0)


def test_empty_input_returns_empty_without_dividing_by_zero():
    stats = compute_speaker_statistics([])
    assert stats["speakers"] == {}
    assert stats["totals"]["num_speakers"] == 0
    assert stats["totals"]["total_speaking_time_sec"] == 0.0


def test_unknown_is_reported_separately_and_not_as_a_speaker():
    """Unattributed speech must neither become a participant nor vanish.

    Counting it as a speaker invents an attendee; dropping it silently inflates
    everyone else's share. Reporting it separately keeps the shares honest and
    makes the caveat visible.
    """
    stats = compute_speaker_statistics(
        [_seg(0, 10, "A"), _seg(10, 20, "B"), _seg(20, 30, UNKNOWN_SPEAKER)]
    )
    assert set(stats["speakers"]) == {"A", "B"}
    assert stats["totals"]["num_speakers"] == 2
    assert stats["totals"]["unattributed_time_sec"] == pytest.approx(10.0)
    assert stats["totals"]["unattributed_pct"] == pytest.approx(33.33, abs=0.01)
    # Shares are over attributed speech only, so these stay at 50/50.
    assert stats["speakers"]["A"]["participation_pct"] == pytest.approx(50.0)


def test_all_unknown_produces_no_speakers_but_records_the_time():
    stats = compute_speaker_statistics([_seg(0, 10, UNKNOWN_SPEAKER)])
    assert stats["speakers"] == {}
    assert stats["totals"]["unattributed_pct"] == pytest.approx(100.0)


def test_missing_speaker_key_is_treated_as_unknown():
    stats = compute_speaker_statistics([{"start": 0, "end": 5, "text": "hi"}])
    assert stats["speakers"] == {}
    assert stats["totals"]["unattributed_time_sec"] == pytest.approx(5.0)


def test_overlapping_speakers_each_get_full_credit():
    """Total speaking time may exceed meeting duration when people talk over each other.

    Apportioning shared seconds is out of scope; the consequence is reported rather
    than hidden, because it is itself a signal about the meeting.
    """
    stats = compute_speaker_statistics([_seg(0, 10, "A"), _seg(0, 10, "B")])
    assert stats["totals"]["total_speaking_time_sec"] == pytest.approx(20.0)


def test_negative_duration_segment_is_clamped_not_subtracted():
    stats = compute_speaker_statistics([_seg(10, 5, "A")])
    assert stats["speakers"]["A"]["speaking_time_sec"] == 0.0


def test_utterance_and_word_counts():
    stats = compute_speaker_statistics(
        [_seg(0, 2, "A", "one two"), _seg(2, 4, "A", "three four five")]
    )
    assert stats["speakers"]["A"]["utterance_count"] == 2
    assert stats["speakers"]["A"]["word_count"] == 5


def test_words_per_minute_and_mean_utterance():
    stats = compute_speaker_statistics([_seg(0, 60, "A", "w " * 120)])
    assert stats["speakers"]["A"]["words_per_minute"] == pytest.approx(120.0)
    assert stats["speakers"]["A"]["mean_utterance_sec"] == pytest.approx(60.0)


def test_zero_duration_segment_does_not_divide_by_zero_in_rate():
    stats = compute_speaker_statistics([_seg(5, 5, "A", "hello")])
    assert stats["speakers"]["A"]["words_per_minute"] == 0.0


@pytest.mark.parametrize(
    ("text", "expected"),
    [("one two", 2), ("  spaced   out  ", 2), ("", 0), ("आज हम मीटिंग", 3)],
)
def test_count_words(text, expected):
    assert count_words(text) == expected


def test_speakers_are_reported_in_sorted_order():
    stats = compute_speaker_statistics([_seg(0, 1, "C"), _seg(1, 2, "A"), _seg(2, 3, "B")])
    assert list(stats["speakers"]) == ["A", "B", "C"]


def test_most_active_speaker():
    stats = compute_speaker_statistics([_seg(0, 5, "A"), _seg(5, 20, "B")])
    assert most_active_speaker(stats) == "B"


def test_most_active_speaker_of_empty_stats_is_none():
    assert most_active_speaker(compute_speaker_statistics([])) is None


def test_statistics_on_the_synthetic_fixture(synthetic_tagged_segments):
    """Sanity check against a realistic 22-segment three-speaker transcript."""
    stats = compute_speaker_statistics(synthetic_tagged_segments)
    assert stats["totals"]["num_speakers"] == 3
    assert sum(s["participation_pct"] for s in stats["speakers"].values()) == pytest.approx(
        100.0, abs=0.05
    )


# ==========================================================================
# Meeting metadata
# ==========================================================================
@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00:00"),
        (59, "00:00:59"),
        (60, "00:01:00"),
        (61, "00:01:01"),
        (3599, "00:59:59"),
        (3600, "01:00:00"),
        (3661, "01:01:01"),
        (-5, "00:00:00"),
        (133.5, "00:02:13"),
    ],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_duration_is_wall_clock_span():
    """Span, not summed speaking time -- the two differ by silence, deliberately."""
    assert compute_duration([_seg(0, 5, "A"), _seg(55, 60, "A")]) == pytest.approx(60.0)


def test_duration_of_empty_transcript_is_zero():
    assert compute_duration([]) == 0.0


def test_duration_uses_extremes_not_first_and_last_element():
    """Robust to out-of-order segments."""
    assert compute_duration([_seg(50, 60, "A"), _seg(0, 10, "A")]) == pytest.approx(60.0)


def test_num_speakers_excludes_unknown():
    segments = [_seg(0, 1, "A"), _seg(1, 2, "B"), _seg(2, 3, UNKNOWN_SPEAKER)]
    assert compute_num_speakers(segments) == 2


def test_num_speakers_of_empty_transcript_is_zero():
    assert compute_num_speakers([]) == 0


def test_languages_used_is_in_presentation_order():
    segments = [
        {"language": "Code-Mixed"},
        {"language": "English"},
        {"language": "Hindi"},
        {"language": "English"},
    ]
    assert compute_languages_used(segments) == ["English", "Hindi", "Code-Mixed"]


def test_languages_used_is_empty_when_untagged():
    """Correct before language tagging runs; guessing would duplicate that stage."""
    assert compute_languages_used([_seg(0, 1, "A")]) == []


def test_unexpected_language_labels_are_appended_alphabetically():
    segments = [{"language": "Hindi"}, {"language": "Marathi"}, {"language": "Bengali"}]
    assert compute_languages_used(segments) == ["Hindi", "Bengali", "Marathi"]


def test_total_word_count():
    assert compute_total_word_count([_seg(0, 1, "A", "one two"), _seg(1, 2, "B", "three")]) == 3


def test_meeting_id_shape():
    assert generate_meeting_id().startswith("MTG-")
    assert len(generate_meeting_id()) == len("MTG-20260925-141203")


def test_generate_metadata_accepts_caller_supplied_identity():
    """Date and time are not in the transcript; the caller must be able to set them."""
    metadata = generate_metadata(
        [_seg(0, 10, "A")], meeting_id="MTG-CUSTOM", date="2026-01-02", time="09:30:00"
    )
    assert metadata["meeting_id"] == "MTG-CUSTOM"
    assert metadata["date"] == "2026-01-02"
    assert metadata["time"] == "09:30:00"


def test_generate_metadata_fills_in_defaults():
    metadata = generate_metadata([_seg(0, 10, "A")])
    assert metadata["meeting_id"].startswith("MTG-")
    assert metadata["date"]
    assert metadata["time"]


def test_generate_metadata_on_empty_transcript():
    metadata = generate_metadata([])
    assert metadata["duration_sec"] == 0.0
    assert metadata["duration_readable"] == "00:00:00"
    assert metadata["num_speakers"] == 0
    assert metadata["languages_used"] == []
    assert metadata["segment_count"] == 0


def test_generate_metadata_on_the_synthetic_fixture(synthetic_tagged_segments):
    metadata = generate_metadata(synthetic_tagged_segments)
    assert metadata["num_speakers"] == 3
    assert metadata["segment_count"] == 22
    assert set(metadata["languages_used"]) <= {"English", "Hindi", "Code-Mixed"}


def test_duration_and_speaking_time_are_expected_to_disagree():
    """Documents the relationship between the two modules' duration figures."""
    segments = [_seg(0, 5, "A"), _seg(55, 60, "A")]
    span = compute_duration(segments)
    speaking = compute_speaker_statistics(segments)["totals"]["total_speaking_time_sec"]
    assert span == pytest.approx(60.0)
    assert speaking == pytest.approx(10.0)
    assert span > speaking
