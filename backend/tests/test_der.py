"""Tests for diarization error rate, against small hand-built turn lists."""

from __future__ import annotations

import pytest

from meeting_assistant.evaluation.der import diarization_error_rate


def test_identical_turns_have_zero_der():
    turns = [
        {"start": 0.0, "end": 5.0, "speaker": "A"},
        {"start": 5.0, "end": 10.0, "speaker": "B"},
    ]
    result = diarization_error_rate(turns, turns)
    assert result.der == 0.0
    assert result.confusion == 0.0
    assert result.missed_detection == 0.0
    assert result.false_alarm == 0.0


def test_permuted_speaker_labels_still_score_zero_der():
    """DER matches labels by optimal overlap, not by name -- a hypothesis
    using entirely different label text for the same two speakers in the
    same regions must not be penalized as confusion."""
    reference = [
        {"start": 0.0, "end": 5.0, "speaker": "A"},
        {"start": 5.0, "end": 10.0, "speaker": "B"},
    ]
    hypothesis = [
        {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},
        {"start": 5.0, "end": 10.0, "speaker": "SPEAKER_01"},
    ]
    result = diarization_error_rate(reference, hypothesis)
    assert result.der == 0.0


def test_missed_detection_when_hypothesis_has_a_gap():
    reference = [{"start": 0.0, "end": 10.0, "speaker": "A"}]
    hypothesis = [{"start": 0.0, "end": 6.0, "speaker": "A"}]  # last 4s undetected
    result = diarization_error_rate(reference, hypothesis, collar=0.0)
    assert result.missed_detection == pytest.approx(4.0)
    assert result.der > 0.0


def test_false_alarm_when_hypothesis_has_extra_speech():
    reference = [{"start": 0.0, "end": 5.0, "speaker": "A"}]
    hypothesis = [{"start": 0.0, "end": 8.0, "speaker": "A"}]  # 3s of nothing
    result = diarization_error_rate(reference, hypothesis, collar=0.0)
    assert result.false_alarm == pytest.approx(3.0)


def test_confusion_when_a_region_is_attributed_to_the_wrong_speaker():
    reference = [
        {"start": 0.0, "end": 5.0, "speaker": "A"},
        {"start": 5.0, "end": 10.0, "speaker": "B"},
    ]
    hypothesis = [
        {"start": 0.0, "end": 5.0, "speaker": "A"},
        {"start": 5.0, "end": 10.0, "speaker": "A"},  # should have been B
    ]
    result = diarization_error_rate(reference, hypothesis, collar=0.0)
    assert result.confusion == pytest.approx(5.0)


def test_collar_excuses_small_boundary_disagreement():
    reference = [{"start": 0.0, "end": 5.0, "speaker": "A"}]
    hypothesis = [{"start": 0.1, "end": 4.9, "speaker": "A"}]  # 0.1s off each edge
    result = diarization_error_rate(reference, hypothesis, collar=0.25)
    assert result.der == 0.0


def test_both_empty_is_perfect_agreement():
    result = diarization_error_rate([], [])
    assert result.der == 0.0
    assert result.total == 0.0


def test_as_dict_reports_collar_and_rounds_der():
    result = diarization_error_rate(
        [{"start": 0.0, "end": 5.0, "speaker": "A"}],
        [{"start": 0.0, "end": 5.0, "speaker": "A"}],
        collar=0.25,
    )
    d = result.as_dict()
    assert d["collar"] == 0.25
    assert d["der"] == round(d["der"], 4)
