"""Tests for cross-chunk speaker identity resolution metrics."""

from __future__ import annotations

import pytest

from meeting_assistant.align.stitch import RESOLUTION_GLOBAL, RESOLUTION_UNRESOLVED
from meeting_assistant.evaluation.registry_metrics import (
    identity_accuracy,
    registry_summary_metrics,
)


def _seg(start, end, speaker, true_speaker=None, **extra):
    d = {"start": start, "end": end, "speaker": speaker}
    if true_speaker is not None:
        d["true_speaker"] = true_speaker
    d.update(extra)
    return d


# ---------------------------------------------------------------------------
# identity_accuracy
# ---------------------------------------------------------------------------
def test_perfect_mapping_scores_full_accuracy_even_with_different_label_names():
    segments = [
        _seg(0, 5, "SPEAKER_G01", true_speaker="Riya"),
        _seg(5, 10, "SPEAKER_G02", true_speaker="Karan"),
        _seg(10, 15, "SPEAKER_G01", true_speaker="Riya"),
    ]
    assert identity_accuracy(segments) == 1.0


def test_fully_swapped_labels_still_scores_full_accuracy_under_optimal_mapping():
    """The whole point: SPEAKER_G01 consistently meaning Karan (not Riya) is
    still a perfect, useful mapping -- it just needs the right permutation."""
    segments = [
        _seg(0, 5, "SPEAKER_G01", true_speaker="Karan"),
        _seg(5, 10, "SPEAKER_G02", true_speaker="Riya"),
        _seg(10, 15, "SPEAKER_G01", true_speaker="Karan"),
    ]
    assert identity_accuracy(segments) == 1.0


def test_fragmented_identity_lowers_accuracy_proportionally_to_duration():
    """Riya's voice was split into two global ids (fragmentation) -- half her
    speaking time (by duration) is 'wrong' under the best single mapping."""
    segments = [
        _seg(0, 5, "SPEAKER_G01", true_speaker="Riya"),
        _seg(5, 10, "SPEAKER_G02", true_speaker="Riya"),  # same person, new id
        _seg(10, 15, "SPEAKER_G03", true_speaker="Karan"),
    ]
    # Best mapping: G01->Riya (5s), G03->Karan (5s) = 10s matched of 15s total.
    assert identity_accuracy(segments) == pytest.approx(10 / 15)


def test_accuracy_is_duration_weighted_not_segment_count_weighted():
    segments = [
        _seg(0, 1, "SPEAKER_G01", true_speaker="Riya"),  # 1s correct
        _seg(1, 2, "SPEAKER_G02", true_speaker="Riya"),  # 1s wrong (fragmented)
        _seg(2, 20, "SPEAKER_G01", true_speaker="Riya"),  # 18s correct
    ]
    # Majority-duration id for Riya is G01: matched = 1 + 18 = 19 of 20s.
    assert identity_accuracy(segments) == pytest.approx(19 / 20)


def test_segments_without_true_speaker_are_ignored():
    segments = [
        _seg(0, 5, "SPEAKER_G01", true_speaker="Riya"),
        _seg(5, 10, "SPEAKER_G01"),  # no ground truth -- excluded
    ]
    assert identity_accuracy(segments) == 1.0


def test_no_ground_truth_at_all_returns_zero_rather_than_raising():
    segments = [_seg(0, 5, "SPEAKER_G01")]
    assert identity_accuracy(segments) == 0.0


def test_empty_segments_returns_zero():
    assert identity_accuracy([]) == 0.0


# ---------------------------------------------------------------------------
# registry_summary_metrics
# ---------------------------------------------------------------------------
def test_summary_reports_unresolved_rate():
    segments = [
        _seg(0, 5, "SPEAKER_G01", speaker_resolution=RESOLUTION_GLOBAL),
        _seg(5, 10, "C1_SPEAKER_00", speaker_resolution=RESOLUTION_UNRESOLVED),
        _seg(10, 15, "C1_SPEAKER_01", speaker_resolution=RESOLUTION_UNRESOLVED),
        _seg(15, 20, "SPEAKER_G02", speaker_resolution=RESOLUTION_GLOBAL),
    ]
    result = registry_summary_metrics(segments)
    assert result.unresolved_rate == 0.5


def test_summary_reports_mean_match_similarity_over_resolved_segments_only():
    segments = [
        _seg(0, 5, "SPEAKER_G01", speaker_resolution=RESOLUTION_GLOBAL, speaker_confidence=0.9),
        _seg(5, 10, "SPEAKER_G01", speaker_resolution=RESOLUTION_GLOBAL, speaker_confidence=0.7),
        _seg(10, 15, "C1_SPEAKER_00", speaker_resolution=RESOLUTION_UNRESOLVED),
    ]
    result = registry_summary_metrics(segments)
    assert result.mean_match_similarity == pytest.approx(0.8)


def test_summary_without_any_confidence_reports_none():
    segments = [_seg(0, 5, "C1_SPEAKER_00", speaker_resolution=RESOLUTION_UNRESOLVED)]
    result = registry_summary_metrics(segments)
    assert result.mean_match_similarity is None


def test_summary_without_ground_truth_reports_none_identity_accuracy():
    segments = [_seg(0, 5, "SPEAKER_G01", speaker_resolution=RESOLUTION_GLOBAL)]
    result = registry_summary_metrics(segments)
    assert result.identity_accuracy is None
    assert result.true_speaker_count is None


def test_summary_with_ground_truth_computes_identity_accuracy_and_true_count():
    segments = [
        _seg(0, 5, "SPEAKER_G01", true_speaker="Riya", speaker_resolution=RESOLUTION_GLOBAL),
        _seg(5, 10, "SPEAKER_G02", true_speaker="Karan", speaker_resolution=RESOLUTION_GLOBAL),
    ]
    result = registry_summary_metrics(segments)
    assert result.identity_accuracy == 1.0
    assert result.true_speaker_count == 2


def test_explicit_true_speaker_count_overrides_the_inferred_one():
    """A third real attendee who never got a global id resolved (e.g. only
    ever below MIN_EMBED_SEC) must still be countable via the attendee list,
    not silently invisible because no segment happened to name them."""
    segments = [
        _seg(0, 5, "SPEAKER_G01", true_speaker="Riya", speaker_resolution=RESOLUTION_GLOBAL),
    ]
    result = registry_summary_metrics(segments, true_speaker_count=3)
    assert result.true_speaker_count == 3


def test_predicted_speaker_count_counts_distinct_labels_including_unresolved():
    segments = [
        _seg(0, 5, "SPEAKER_G01", speaker_resolution=RESOLUTION_GLOBAL),
        _seg(5, 10, "C1_SPEAKER_00", speaker_resolution=RESOLUTION_UNRESOLVED),
    ]
    result = registry_summary_metrics(segments)
    assert result.predicted_speaker_count == 2


def test_summary_of_empty_segments_does_not_crash():
    result = registry_summary_metrics([])
    assert result.unresolved_rate == 0.0
    assert result.predicted_speaker_count == 0
