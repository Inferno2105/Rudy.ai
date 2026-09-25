"""Summarization and action-item extraction quality metrics.

Two different problems, two different comparisons. Summarization produces
free text, so :func:`summary_rouge` scores n-gram overlap against a reference
summary via ``rouge_score`` — a proxy for content coverage, always meant to be
read alongside the paper's human rubric (faithfulness, coverage, no
hallucination), not as a replacement for it. Action-item extraction produces
structured records, so :func:`action_item_metrics` can score something ROUGE
cannot: precision, recall and F1 on whether the *right* (person, task,
deadline) triples were found at all.

Both operate on the pipeline's actual English-language output: the
summarization prompt forces English regardless of input language ("summarize
in clear English" — see ``llm/prompts.py``), so unlike
:mod:`meeting_assistant.evaluation.asr_metrics`, there is no Hinglish
cross-script comparison problem here for either metric to work around.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from meeting_assistant.evaluation.text_norm import normalize_text

DEFAULT_TASK_SIMILARITY_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------
@dataclass
class RougeResult:
    rouge1_f: float
    rouge2_f: float
    rougeL_f: float
    rouge1_precision: float
    rouge1_recall: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "rouge1_f": round(self.rouge1_f, 4),
            "rouge2_f": round(self.rouge2_f, 4),
            "rougeL_f": round(self.rougeL_f, 4),
            "rouge1_precision": round(self.rouge1_precision, 4),
            "rouge1_recall": round(self.rouge1_recall, 4),
        }


def summary_rouge(reference: str, hypothesis: str) -> RougeResult:
    """ROUGE-1/2/L F-measure (plus ROUGE-1 precision/recall) against a
    hand-written reference summary. ``rouge_score`` does its own
    tokenization and stemming, so text is passed through as-is rather than
    ``evaluation.text_norm`` first."""
    from rouge_score import rouge_scorer

    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)
    scores = scorer.score(reference, hypothesis)
    return RougeResult(
        rouge1_f=scores["rouge1"].fmeasure,
        rouge2_f=scores["rouge2"].fmeasure,
        rougeL_f=scores["rougeL"].fmeasure,
        rouge1_precision=scores["rouge1"].precision,
        rouge1_recall=scores["rouge1"].recall,
    )


# ---------------------------------------------------------------------------
# Action items
# ---------------------------------------------------------------------------
def _token_set(text: str | None) -> set[str]:
    return set(normalize_text(text).split()) if text else set()


def _task_similarity(a: str | None, b: str | None) -> float:
    """Jaccard similarity over normalized word sets.

    Not exact string equality: an extracted action item and its hand-labelled
    reference are independent descriptions of the same task ("send the notes
    to the team" vs "share notes with team"), and scoring only verbatim
    matches would measure paraphrase-avoidance rather than extraction
    quality. Both-empty is treated as a perfect match (1.0); exactly one
    empty is a total mismatch (0.0) rather than an undefined division.
    """
    set_a, set_b = _token_set(a), _token_set(b)
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _persons_compatible(a: str | None, b: str | None) -> bool:
    """Person only gates a match when *both* sides actually name someone.

    A missing person on either side must not block matching on task content
    alone: "who" and "what" are different parts of extraction, and a missed
    or hallucinated person is already visible in ``deadline_accuracy``'s
    sibling statistic (a per-field breakdown a caller can add) rather than
    needing to also suppress an otherwise-correct task match.
    """
    if not a or not b:
        return True
    return normalize_text(a) == normalize_text(b)


@dataclass
class ActionItemMatchResult:
    precision: float
    recall: float
    f1: float
    matched: int
    predicted_count: int
    reference_count: int
    deadline_accuracy: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "matched": self.matched,
            "predicted_count": self.predicted_count,
            "reference_count": self.reference_count,
            "deadline_accuracy": (
                round(self.deadline_accuracy, 4) if self.deadline_accuracy is not None else None
            ),
        }


def action_item_metrics(
    predicted: list[dict[str, Any]],
    reference: list[dict[str, Any]],
    *,
    task_similarity_threshold: float = DEFAULT_TASK_SIMILARITY_THRESHOLD,
) -> ActionItemMatchResult:
    """Precision/recall/F1 on (person, task, deadline) triples.

    Matching is greedy in predicted order: each predicted item is matched to
    its best remaining, person-compatible reference item if that pair's task
    similarity clears ``task_similarity_threshold``. Deterministic for a
    fixed predicted-item order (the order the LLM produced them in) and
    simple enough to check by hand against a small example — a property that
    matters more than optimality here, since a metric a reviewer cannot
    verify by hand is not one they will trust.

    Precision/recall conventions for the empty-set edge cases: recall is
    ``1.0`` whenever there was nothing to find (``reference_count == 0``),
    regardless of what was predicted; precision is ``1.0`` only when nothing
    was predicted *and* nothing needed to be, otherwise ``0.0`` when nothing
    was predicted but something was missed.
    """
    unmatched = list(reference)
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []

    for pred_item in predicted:
        best_index = None
        best_similarity = -1.0
        for idx, ref_item in enumerate(unmatched):
            if not _persons_compatible(pred_item.get("person"), ref_item.get("person")):
                continue
            similarity = _task_similarity(pred_item.get("task"), ref_item.get("task"))
            if similarity > best_similarity:
                best_similarity, best_index = similarity, idx

        if best_index is not None and best_similarity >= task_similarity_threshold:
            matched_pairs.append((pred_item, unmatched.pop(best_index)))

    matched = len(matched_pairs)
    predicted_count = len(predicted)
    reference_count = len(reference)

    if predicted_count == 0:
        precision = 1.0 if reference_count == 0 else 0.0
    else:
        precision = matched / predicted_count
    recall = 1.0 if reference_count == 0 else matched / reference_count
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    if matched:
        deadline_hits = sum(
            1
            for pred_item, ref_item in matched_pairs
            if normalize_text(pred_item.get("deadline") or "")
            == normalize_text(ref_item.get("deadline") or "")
        )
        deadline_accuracy = deadline_hits / matched
    else:
        deadline_accuracy = None

    return ActionItemMatchResult(
        precision=precision,
        recall=recall,
        f1=f1,
        matched=matched,
        predicted_count=predicted_count,
        reference_count=reference_count,
        deadline_accuracy=deadline_accuracy,
    )
