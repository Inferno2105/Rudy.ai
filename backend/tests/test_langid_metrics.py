"""Tests for language-ID classification metrics, against hand-built label lists."""

from __future__ import annotations

import math

from meeting_assistant.evaluation.langid_metrics import classification_metrics, cohens_kappa


def test_perfect_agreement_has_accuracy_one():
    y_true = ["English", "Hindi", "Code-Mixed", "Hindi"]
    result = classification_metrics(y_true, y_true)
    assert result.accuracy == 1.0
    for label in result.labels:
        assert result.per_class[label]["f1"] == 1.0


def test_accuracy_counts_exact_matches():
    y_true = ["English", "Hindi", "Hindi", "English"]
    y_pred = ["English", "Hindi", "English", "English"]  # 3/4 correct
    result = classification_metrics(y_true, y_pred)
    assert result.accuracy == 0.75


def test_confusion_matrix_reports_the_specific_misclassification():
    y_true = ["Hindi", "Hindi", "English"]
    y_pred = ["English", "Hindi", "English"]  # one Hindi misread as English
    result = classification_metrics(y_true, y_pred)
    assert result.confusion["Hindi"]["English"] == 1
    assert result.confusion["Hindi"]["Hindi"] == 1
    assert result.confusion["English"]["English"] == 1


def test_a_label_that_only_appears_in_predictions_is_included():
    y_true = ["English", "English"]
    y_pred = ["English", "Code-Mixed"]  # tagger over-predicted Code-Mixed
    result = classification_metrics(y_true, y_pred)
    assert "Code-Mixed" in result.labels
    # 0 of the 1 predicted Code-Mixed segments were actually Code-Mixed.
    assert result.per_class["Code-Mixed"]["precision"] == 0.0


def test_empty_input_reports_zero_accuracy_without_crashing():
    result = classification_metrics([], [])
    assert result.accuracy == 0.0
    assert result.labels == []


def test_as_dict_rounds_floats_and_keeps_integer_support():
    result = classification_metrics(["English", "Hindi"], ["English", "Hindi"])
    d = result.as_dict()
    for label in d["labels"]:
        assert isinstance(d["per_class"][label]["support"], int)
        assert d["per_class"][label]["f1"] == round(d["per_class"][label]["f1"], 4)


# ---------------------------------------------------------------------------
# cohens_kappa
# ---------------------------------------------------------------------------
def test_identical_labels_from_two_annotators_using_multiple_classes_is_kappa_one():
    labels = ["English", "Hindi", "English", "Hindi"]
    assert cohens_kappa(labels, labels) == 1.0


def test_completely_reversed_labels_is_negative_kappa():
    a = ["English", "Hindi", "English", "Hindi"]
    b = ["Hindi", "English", "Hindi", "English"]
    assert cohens_kappa(a, b) < 0


def test_kappa_is_nan_when_both_annotators_use_a_single_constant_label():
    """Not 1.0: with only one label in play, chance agreement is also 100%,
    so agreement-corrected-for-chance is mathematically undefined."""
    a = ["English", "English", "English"]
    result = cohens_kappa(a, a)
    assert math.isnan(result)


def test_kappa_of_empty_input_is_nan_not_a_crash():
    assert math.isnan(cohens_kappa([], []))
