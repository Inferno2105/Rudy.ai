"""Diarization Error Rate, via ``pyannote.metrics``.

DER decomposes into three components — confusion (speech attributed to the
wrong speaker), missed detection (a real turn with no matching hypothesis
turn) and false alarm (a hypothesis turn with no real speech there) — and
reporting only the combined percentage hides which failure mode actually
dominates a given clip. A collar of 0.25s (``pyannote.metrics``' own
recommended default) excuses turn-boundary disagreement within a quarter
second on either side of a reference boundary, since a human labeller's
boundary and the diarizer's are never going to agree to the millisecond and
should not be penalized as if they were a mid-word error.

Speaker labels are matched optimally, not by name: ``pyannote.metrics`` finds
the one-to-one mapping between reference and hypothesis labels that minimizes
error before computing confusion, so a hypothesis using ``SPEAKER_00``/
``SPEAKER_01`` and a reference using ``A``/``B`` for the same two people score
correctly regardless of the label text — confirmed with real permuted labels
during development, not assumed from the library's documentation.

Reference and hypothesis are both plain ``{"start", "end", "speaker"}``
segment lists — the diarizer's own output shape, and what
:mod:`meeting_assistant.evaluation.rttm` reads back from an RTTM file or an
Audacity label export — converted to ``pyannote.core.Annotation`` only at the
point ``pyannote.metrics`` actually needs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_COLLAR = 0.25


@dataclass
class DiarizationErrorResult:
    der: float
    confusion: float
    missed_detection: float
    false_alarm: float
    total: float
    collar: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "der": round(self.der, 4),
            "confusion": round(self.confusion, 3),
            "missed_detection": round(self.missed_detection, 3),
            "false_alarm": round(self.false_alarm, 3),
            "total": round(self.total, 3),
            "collar": self.collar,
        }


def _to_annotation(segments: list[dict[str, Any]]) -> Any:
    from pyannote.core import Annotation, Segment

    annotation = Annotation()
    for segment in segments:
        if segment["end"] > segment["start"]:
            annotation[Segment(segment["start"], segment["end"])] = segment["speaker"]
    return annotation


def diarization_error_rate(
    reference: list[dict[str, Any]],
    hypothesis: list[dict[str, Any]],
    *,
    collar: float = DEFAULT_COLLAR,
) -> DiarizationErrorResult:
    """DER of ``hypothesis`` against ``reference``, with its component breakdown.

    Both empty is treated as perfect agreement (``der=0.0``) by
    ``pyannote.metrics`` itself, not specially handled here.
    """
    from pyannote.metrics.diarization import DiarizationErrorRate

    metric = DiarizationErrorRate(collar=collar)
    detail = metric(_to_annotation(reference), _to_annotation(hypothesis), detailed=True)

    return DiarizationErrorResult(
        der=detail["diarization error rate"],
        confusion=detail["confusion"],
        missed_detection=detail["missed detection"],
        false_alarm=detail["false alarm"],
        total=detail["total"],
        collar=collar,
    )
