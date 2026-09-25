"""Tests for flattening a transcript into LLM-prompt text."""

from __future__ import annotations

import pytest

from meeting_assistant.intel.transcript_text import build_transcript_text, format_timestamp


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "00:00"), (5, "00:05"), (65, "01:05"), (3661, "61:01"), (-3, "00:00")],
)
def test_format_timestamp(seconds, expected):
    assert format_timestamp(seconds) == expected


def test_builds_one_line_per_segment():
    segments = [
        {"start": 0, "speaker": "SPEAKER_00", "text": "Good morning."},
        {"start": 5, "speaker": "SPEAKER_01", "text": "Hello there."},
    ]
    text = build_transcript_text(segments)
    assert text == "[00:00] SPEAKER_00: Good morning.\n[00:05] SPEAKER_01: Hello there."


def test_skips_segments_with_empty_text():
    """A blank line costs prompt tokens and tells the model nothing."""
    segments = [
        {"start": 0, "speaker": "A", "text": "hello"},
        {"start": 5, "speaker": "B", "text": "   "},
        {"start": 10, "speaker": "C", "text": ""},
    ]
    text = build_transcript_text(segments)
    assert text == "[00:00] A: hello"


def test_missing_speaker_falls_back_to_unknown():
    text = build_transcript_text([{"start": 0, "text": "hi"}])
    assert text == "[00:00] UNKNOWN: hi"


def test_empty_transcript_produces_empty_string():
    assert build_transcript_text([]) == ""


def test_synthetic_fixture_produces_a_nonempty_multiline_transcript(
    synthetic_tagged_segments,
):
    text = build_transcript_text(synthetic_tagged_segments)
    assert text.count("\n") == 21  # 22 segments -> 21 newlines
    assert text.startswith("[00:00]")
