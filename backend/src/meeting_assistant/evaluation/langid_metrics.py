"""Language-ID classification metrics: accuracy, per-class precision/recall/
F1, a confusion matrix, and Cohen's kappa for inter-annotator agreement.

The language tagger (:mod:`meeting_assistant.language.detection`) classifies
each segment as English, Hindi or Code-Mixed by Unicode script composition —
a documented heuristic, not a trained classifier, and one with a known
limitation (Romanized Hindi reads as English). :func:`classification_metrics`
is what turns "we know it has a limitation" into "here is exactly how often,
and confused with what," against a hand-labelled reference.

:func:`cohens_kappa` exists for the ~20% double-labelled subset the dataset
protocol calls for (see ``docs/evaluation.md``): reviewers reasonably ask
whether a single annotator's categorical labels are even consistent with a
second opinion, and reporting only the tagger's accuracy against one set of
labels cannot answer that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class LangIdMetrics:
    """Accuracy plus the per-class and confusion breakdown, for the manifest."""

    accuracy: float
    per_class: dict[str, dict[str, float]]
    confusion: dict[str, dict[str, int]]
    labels: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "accuracy": round(self.accuracy, 4),
            "per_class": {
                label: {
                    "precision": round(values["precision"], 4),
                    "recall": round(values["recall"], 4),
                    "f1": round(values["f1"], 4),
                    "support": values["support"],
                }
                for label, values in self.per_class.items()
            },
            "confusion": self.confusion,
            "labels": self.labels,
        }


def classification_metrics(y_true: list[str], y_pred: list[str]) -> LangIdMetrics:
    """Accuracy, per-class P/R/F1, and a confusion matrix.

    ``labels`` is the union of every label seen in either list, sorted, so a
    class the tagger over- or under-predicts (appearing in only one of the
    two lists) still shows up in the confusion matrix rather than being
    silently dropped.

    Args:
        y_true: reference labels, one per segment.
        y_pred: the tagger's labels, same length and order as ``y_true``.
    """
    from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

    if not y_true:
        return LangIdMetrics(accuracy=0.0, per_class={}, confusion={}, labels=[])

    labels = sorted(set(y_true) | set(y_pred))
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, zero_division=0
    )
    accuracy = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == p) / len(y_true)

    per_class = {
        label: {
            "precision": float(precision[i]),
            "recall": float(recall[i]),
            "f1": float(f1[i]),
            "support": int(support[i]),
        }
        for i, label in enumerate(labels)
    }

    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    confusion = {
        true_label: {
            pred_label: int(matrix[i][j]) for j, pred_label in enumerate(labels)
        }
        for i, true_label in enumerate(labels)
    }

    return LangIdMetrics(accuracy=accuracy, per_class=per_class, confusion=confusion, labels=labels)


def cohens_kappa(labels_a: list[str], labels_b: list[str]) -> float:
    """Inter-annotator agreement between two labellers of the same segments.

    Returns ``float("nan")``, not ``1.0``, when both annotators used only one
    label throughout their overlap — kappa corrects observed agreement for
    the agreement expected by chance, and when there is only one possible
    label, chance agreement is also 100%, making the statistic mathematically
    undefined rather than perfect. Callers reporting this number should
    surface that NaN rather than treating it as a successful measurement.
    """
    from sklearn.metrics import cohen_kappa_score

    if not labels_a:
        return float("nan")
    return round(float(cohen_kappa_score(labels_a, labels_b)), 4)
