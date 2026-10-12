"""Tests for report assembly: which metric families get included, and how
cross-clip aggregation handles missing data."""

from __future__ import annotations

import pytest

from meeting_assistant.evaluation.report import (
    ClipHypothesis,
    ClipReference,
    aggregate_reports,
    generate_clip_report,
)


def test_a_family_is_included_only_when_both_sides_are_present():
    hyp = ClipHypothesis(transcript_text="good morning")
    ref = ClipReference(transcript_text="good morning")
    report = generate_clip_report("clip01", hyp, ref)
    assert "asr" in report
    assert "diarization" not in report
    assert "summary" not in report


def test_hypothesis_without_reference_is_not_scored():
    hyp = ClipHypothesis(summary="a summary nobody labelled a reference for")
    ref = ClipReference()
    report = generate_clip_report("clip01", hyp, ref)
    assert "summary" not in report


def test_reference_without_hypothesis_is_not_scored():
    hyp = ClipHypothesis()
    ref = ClipReference(summary="reference summary, but the stage never ran")
    report = generate_clip_report("clip01", hyp, ref)
    assert "summary" not in report


def test_asr_family_contains_all_three_wer_variants():
    hyp = ClipHypothesis(transcript_text="namaste duniya")
    ref = ClipReference(transcript_text="namaste duniya")
    report = generate_clip_report("clip01", hyp, ref)
    assert set(report["asr"].keys()) == {"wer_raw", "wer_romanized", "cer_raw"}


def test_true_speakers_come_from_the_reference_turns_by_time():
    hyp = ClipHypothesis(
        resolved_segments=[
            {"start": 0.0, "end": 5.0, "speaker": "SPEAKER_G01"},
            {"start": 5.0, "end": 10.0, "speaker": "SPEAKER_G02"},
        ]
    )
    ref = ClipReference(
        turns=[
            {"start": 0.0, "end": 5.2, "speaker": "Riya"},
            {"start": 5.2, "end": 10.0, "speaker": "Karan"},
        ]
    )
    report = generate_clip_report("clip01", hyp, ref)
    assert report["registry"]["identity_accuracy"] == 1.0
    assert report["registry"]["true_speaker_count"] == 2


def test_language_is_scored_by_time_overlap_not_position():
    """A run that cuts the audio differently is still scored against the same labels."""
    hyp = ClipHypothesis(
        resolved_segments=[
            {"start": 0.0, "end": 3.0, "speaker": "A", "language": "Hindi"},
            {"start": 3.0, "end": 4.0, "speaker": "A", "language": "English"},
            {"start": 4.0, "end": 9.0, "speaker": "B", "language": "Hindi"},
            {"start": 20.0, "end": 21.0, "speaker": "B", "language": "English"},
        ]
    )
    ref = ClipReference(
        language_spans=[
            {"start": 0.0, "end": 3.5, "language": "Hindi"},
            {"start": 3.5, "end": 9.0, "language": "Code-Mixed"},
        ]
    )
    language = generate_clip_report("clip01", hyp, ref)["language_id"]
    # Segment 2 overlaps Hindi 0.5 s and Code-Mixed 0.5 s: the first longest wins (Hindi).
    # Segment 4 overlaps no label and is not scored.
    assert language["segments_scored"] == 3
    assert language["segments_total"] == 4
    assert language["accuracy"] == 0.3333  # reported to 4 decimals


def test_system_metrics_pass_through_unchanged():
    hyp = ClipHypothesis(system_metrics={"realtime_factor": 0.42})
    report = generate_clip_report("clip01", hyp, ClipReference())
    assert report["system"] == {"realtime_factor": 0.42}


def test_clip_id_is_always_present():
    report = generate_clip_report("clip07", ClipHypothesis(), ClipReference())
    assert report["clip_id"] == "clip07"


# ---------------------------------------------------------------------------
# aggregate_reports
# ---------------------------------------------------------------------------
def test_aggregate_averages_a_numeric_leaf_across_clips():
    reports = [
        {"clip_id": "a", "asr": {"wer_raw": {"wer": 0.2}}},
        {"clip_id": "b", "asr": {"wer_raw": {"wer": 0.4}}},
    ]
    aggregated = aggregate_reports(reports)
    assert aggregated["asr"]["wer_raw"]["wer"] == pytest.approx(0.3)
    assert aggregated["num_clips"] == 2


def test_aggregate_skips_clips_missing_a_family_entirely():
    reports = [
        {"clip_id": "a", "summary": {"rouge1_f": 0.8}},
        {"clip_id": "b"},  # Ollama was down for this run -- no summary at all
        {"clip_id": "c", "summary": {"rouge1_f": 0.6}},
    ]
    aggregated = aggregate_reports(reports)
    # Mean of 0.8 and 0.6 only -- clip b must not count as a 0.0.
    assert aggregated["summary"]["rouge1_f"] == pytest.approx(0.7)


def test_aggregate_of_no_reports_at_all_has_zero_clips():
    aggregated = aggregate_reports([])
    assert aggregated == {"num_clips": 0}


def test_aggregate_reports_agreed_non_numeric_value_unchanged():
    reports = [
        {"clip_id": "a", "diarization": {"collar": 0.25}},
        {"clip_id": "b", "diarization": {"collar": 0.25}},
    ]
    aggregated = aggregate_reports(reports)
    assert aggregated["diarization"]["collar"] == 0.25


def test_aggregate_omits_disagreeing_non_numeric_values():
    reports = [
        {"clip_id": "a", "language_id": {"labels": ["English", "Hindi"]}},
        {"clip_id": "b", "language_id": {"labels": ["English", "Hindi", "Code-Mixed"]}},
    ]
    aggregated = aggregate_reports(reports)
    assert aggregated["language_id"]["labels"] is None
