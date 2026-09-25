"""Cross-chunk speaker identity resolution metrics.

:mod:`meeting_assistant.diarize.speaker_registry` resolves chunk-local
diarization labels to stable identities across independently-processed
chunks (live capture's actual situation — see that module's docstring). This
module measures how well it did, against a ground-truth mapping from segment
to real speaker identity.

``identity_accuracy`` reuses the same principle
:mod:`meeting_assistant.evaluation.der` uses for diarization: a predicted
label and a true label describe the same person as long as there is *some*
consistent one-to-one mapping between them, regardless of what the predicted
label is actually named (``SPEAKER_G01`` vs ``"Riya"``). Found here via the
Hungarian algorithm (``scipy.optimize.linear_sum_assignment``) over a
duration-weighted contingency table, rather than DER's time-overlap table,
since resolved segments are already discrete units by the time this runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RegistryMetrics:
    """One run's speaker-resolution quality, for the evaluation report."""

    identity_accuracy: float | None
    predicted_speaker_count: int
    true_speaker_count: int | None
    unresolved_rate: float
    mean_match_similarity: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "identity_accuracy": (
                round(self.identity_accuracy, 4) if self.identity_accuracy is not None else None
            ),
            "predicted_speaker_count": self.predicted_speaker_count,
            "true_speaker_count": self.true_speaker_count,
            "unresolved_rate": round(self.unresolved_rate, 4),
            "mean_match_similarity": (
                round(self.mean_match_similarity, 4)
                if self.mean_match_similarity is not None
                else None
            ),
        }


def _duration_weighted_contingency(segments: list[dict[str, Any]]) -> Any:
    import numpy as np

    true_labels = sorted({s["true_speaker"] for s in segments})
    pred_labels = sorted({s["speaker"] for s in segments})
    true_index = {label: i for i, label in enumerate(true_labels)}
    pred_index = {label: j for j, label in enumerate(pred_labels)}

    matrix = np.zeros((len(true_labels), len(pred_labels)))
    for segment in segments:
        duration = max(0.0, segment["end"] - segment["start"])
        matrix[true_index[segment["true_speaker"]], pred_index[segment["speaker"]]] += duration
    return matrix


def identity_accuracy(segments: list[dict[str, Any]]) -> float:
    """Duration-weighted accuracy under the optimal predicted-to-true label mapping.

    Args:
        segments: each needs ``start``, ``end``, ``speaker`` (the registry's
            resolved or chunk-prefixed label) and ``true_speaker`` (ground
            truth identity). Segments missing ``true_speaker`` are ignored —
            callers should pre-filter if only a subset of a run is labelled.

    Returns:
        ``0.0`` if no segment carries a ``true_speaker``, rather than raising
        on an empty contingency table.
    """
    from scipy.optimize import linear_sum_assignment

    labelled = [s for s in segments if s.get("true_speaker")]
    if not labelled:
        return 0.0

    matrix = _duration_weighted_contingency(labelled)
    total_duration = matrix.sum()
    if total_duration <= 0:
        return 0.0

    row_idx, col_idx = linear_sum_assignment(-matrix)  # negate: assignment minimizes by default
    matched_duration = matrix[row_idx, col_idx].sum()
    return float(matched_duration / total_duration)


def registry_summary_metrics(
    segments: list[dict[str, Any]],
    *,
    true_speaker_count: int | None = None,
) -> RegistryMetrics:
    """Aggregate speaker-resolution metrics for one run's transcript.

    Args:
        segments: stitched, registry-processed segments — the ``speaker``,
            ``speaker_resolution`` and (when resolved) ``speaker_confidence``
            fields set by
            :mod:`meeting_assistant.diarize.speaker_registry` /
            :mod:`meeting_assistant.align.stitch`. ``true_speaker`` on some or
            all segments enables :func:`identity_accuracy`; without it,
            ``identity_accuracy`` and ``true_speaker_count`` are reported as
            ``None`` rather than a misleading ``0.0``.
        true_speaker_count: pass explicitly when known (e.g. from the
            meeting's attendee list) rather than inferred from however many
            distinct ``true_speaker`` labels happen to appear in ``segments``.
    """
    from meeting_assistant.align.stitch import RESOLUTION_UNRESOLVED

    total = len(segments)
    unresolved = sum(1 for s in segments if s.get("speaker_resolution") == RESOLUTION_UNRESOLVED)
    confidences = [
        s["speaker_confidence"] for s in segments if s.get("speaker_confidence") is not None
    ]
    has_ground_truth = any(s.get("true_speaker") for s in segments)

    if true_speaker_count is not None:
        resolved_true_count: int | None = true_speaker_count
    elif has_ground_truth:
        resolved_true_count = len({s["true_speaker"] for s in segments if s.get("true_speaker")})
    else:
        resolved_true_count = None

    return RegistryMetrics(
        identity_accuracy=(identity_accuracy(segments) if has_ground_truth else None),
        predicted_speaker_count=len({s["speaker"] for s in segments}),
        true_speaker_count=resolved_true_count,
        unresolved_rate=(unresolved / total) if total else 0.0,
        mean_match_similarity=(sum(confidences) / len(confidences)) if confidences else None,
    )
