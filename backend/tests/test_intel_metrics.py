"""Tests for summarization ROUGE and action-item precision/recall/F1,
against small hand-checkable examples."""

from __future__ import annotations

from meeting_assistant.evaluation.intel_metrics import action_item_metrics, summary_rouge


# ---------------------------------------------------------------------------
# summary_rouge
# ---------------------------------------------------------------------------
def test_identical_summaries_score_perfect_rouge():
    text = "The team discussed the backend refactor and agreed on a timeline."
    result = summary_rouge(text, text)
    assert result.rouge1_f == 1.0
    assert result.rougeL_f == 1.0


def test_completely_different_summaries_score_zero_rouge1():
    result = summary_rouge("apples and oranges", "quantum physics lecture notes")
    assert result.rouge1_f == 0.0


def test_partial_overlap_scores_between_zero_and_one():
    result = summary_rouge(
        "The team discussed the backend and agreed on a deadline.",
        "The team discussed the frontend today.",
    )
    assert 0.0 < result.rouge1_f < 1.0


# ---------------------------------------------------------------------------
# action_item_metrics
# ---------------------------------------------------------------------------
def test_identical_items_match_perfectly():
    items = [{"person": "Riya", "task": "send the meeting notes", "deadline": "Friday"}]
    result = action_item_metrics(items, items)
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.f1 == 1.0
    assert result.matched == 1
    assert result.deadline_accuracy == 1.0


def test_paraphrased_task_still_matches_above_threshold():
    predicted = [{"person": "Riya", "task": "send the meeting notes to the team", "deadline": None}]
    reference = [{"person": "Riya", "task": "send meeting notes to team", "deadline": None}]
    result = action_item_metrics(predicted, reference)
    assert result.matched == 1


def test_completely_unrelated_task_does_not_match():
    predicted = [{"person": "Riya", "task": "book a flight", "deadline": None}]
    reference = [{"person": "Riya", "task": "review the budget spreadsheet", "deadline": None}]
    result = action_item_metrics(predicted, reference)
    assert result.matched == 0
    assert result.precision == 0.0
    assert result.recall == 0.0


def test_mismatched_person_blocks_an_otherwise_good_task_match():
    predicted = [{"person": "Riya", "task": "send the meeting notes", "deadline": None}]
    reference = [{"person": "Karan", "task": "send the meeting notes", "deadline": None}]
    result = action_item_metrics(predicted, reference)
    assert result.matched == 0


def test_missing_person_on_one_side_does_not_block_matching():
    predicted = [{"person": None, "task": "send the meeting notes", "deadline": None}]
    reference = [{"person": "Riya", "task": "send the meeting notes", "deadline": None}]
    result = action_item_metrics(predicted, reference)
    assert result.matched == 1


def test_an_extra_predicted_item_lowers_precision_not_recall():
    predicted = [
        {"person": "Riya", "task": "send the meeting notes", "deadline": None},
        {"person": "Karan", "task": "totally unrelated hallucinated task", "deadline": None},
    ]
    reference = [{"person": "Riya", "task": "send the meeting notes", "deadline": None}]
    result = action_item_metrics(predicted, reference)
    assert result.matched == 1
    assert result.precision == 0.5
    assert result.recall == 1.0


def test_a_missed_reference_item_lowers_recall_not_precision():
    predicted = [{"person": "Riya", "task": "send the meeting notes", "deadline": None}]
    reference = [
        {"person": "Riya", "task": "send the meeting notes", "deadline": None},
        {"person": "Karan", "task": "review the budget", "deadline": None},
    ]
    result = action_item_metrics(predicted, reference)
    assert result.matched == 1
    assert result.precision == 1.0
    assert result.recall == 0.5


def test_deadline_accuracy_only_counts_matched_pairs():
    predicted = [{"person": "Riya", "task": "send the meeting notes", "deadline": "Friday"}]
    reference = [{"person": "Riya", "task": "send the meeting notes", "deadline": "Monday"}]
    result = action_item_metrics(predicted, reference)
    assert result.matched == 1
    assert result.deadline_accuracy == 0.0


def test_both_empty_is_a_perfect_score():
    result = action_item_metrics([], [])
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.f1 == 1.0
    assert result.deadline_accuracy is None


def test_nothing_predicted_but_something_expected_is_zero_precision_full_miss():
    reference = [{"person": "Riya", "task": "send the meeting notes", "deadline": None}]
    result = action_item_metrics([], reference)
    assert result.precision == 0.0
    assert result.recall == 0.0


def test_something_predicted_but_nothing_expected_has_perfect_recall():
    predicted = [{"person": "Riya", "task": "hallucinated task", "deadline": None}]
    result = action_item_metrics(predicted, [])
    assert result.recall == 1.0
    assert result.precision == 0.0


def test_as_dict_reports_none_deadline_accuracy_when_nothing_matched():
    result = action_item_metrics(
        [{"person": "A", "task": "x", "deadline": None}],
        [{"person": "B", "task": "totally different", "deadline": None}],
    )
    assert result.as_dict()["deadline_accuracy"] is None


def test_threshold_is_configurable():
    predicted = [{"person": "Riya", "task": "notes", "deadline": None}]
    reference = [
        {"person": "Riya", "task": "notes about the quarterly budget review", "deadline": None}
    ]
    lenient = action_item_metrics(predicted, reference, task_similarity_threshold=0.1)
    strict = action_item_metrics(predicted, reference, task_similarity_threshold=0.9)
    assert lenient.matched == 1
    assert strict.matched == 0
