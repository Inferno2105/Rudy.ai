"""Assemble every metric family into one report, per clip and aggregated.

Everything in this module operates on data the caller has already loaded —
a run's artifacts, a clip's reference files — rather than reading from disk
itself. That keeps :func:`generate_clip_report` and :func:`aggregate_reports`
pure and unit-testable against small hand-built cases with no real dataset,
run directory or model required; the disk-reading and CLI-facing side of
turning ``data/eval/references/<clip_id>/`` into a :class:`ClipReference`
belongs to ``cli/main.py``'s ``eval`` command once real labelled clips exist
to read.

A metric family is included in a clip's report only when **both** the
hypothesis and the reference for it are present. A missing reference is not
scored as a failure and a missing hypothesis is not scored as a success —
either would misrepresent an incomplete evaluation as a complete one, which
matters when reviewers are trusting a per-clip table to mean what it says.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from meeting_assistant.evaluation.asr_metrics import (
    character_error_rate,
    romanized_word_error_rate,
    word_error_rate,
)
from meeting_assistant.evaluation.der import diarization_error_rate
from meeting_assistant.evaluation.intel_metrics import action_item_metrics, summary_rouge
from meeting_assistant.evaluation.langid_metrics import classification_metrics
from meeting_assistant.evaluation.registry_metrics import registry_summary_metrics


@dataclass
class ClipHypothesis:
    """What the pipeline actually produced for one clip. Every field is
    optional, so a report can still be generated from a run that only
    completed some stages (e.g. Ollama was down for the LLM-backed ones)."""

    transcript_text: str | None = None
    turns: list[dict[str, Any]] | None = None
    summary: str | None = None
    action_items: list[dict[str, Any]] | None = None
    resolved_segments: list[dict[str, Any]] | None = None
    # The normalize stage's romanized segments, to show what language ID would
    # see if it ran after romanization (the ordering rule's evidence).
    romanized_segments: list[dict[str, Any]] | None = None
    system_metrics: dict[str, Any] | None = None


@dataclass
class ClipReference:
    """Ground truth for one evaluation clip. Every field is optional for the
    same reason as :class:`ClipHypothesis` — a clip need only carry the
    references for the metric families it is meant to exercise."""

    transcript_text: str | None = None
    turns: list[dict[str, Any]] | None = None
    # Language by time: [{"start", "end", "language"}], labelled without
    # seeing any system output (see evaluation/references.py).
    language_spans: list[dict[str, Any]] | None = None
    summary: str | None = None
    action_items: list[dict[str, Any]] | None = None
    true_speaker_count: int | None = None
    # Human rating of the system's summary, {criterion: 1-3} (rubric.txt).
    summary_rubric: dict[str, int] | None = None


def generate_clip_report(
    clip_id: str, hypothesis: ClipHypothesis, reference: ClipReference
) -> dict[str, Any]:
    """One clip's full metric report, as a plain JSON-serializable dict.

    Language and speaker identity are matched **by time**: each system segment
    takes the reference language its stretch contains
    (:func:`~meeting_assistant.evaluation.references.language_at`) and the true
    speaker (``turns``) that overlaps it the longest. Segments that overlap no reference
    label (silence, or speech the annotator left out) are not scored, and the
    number scored is reported, so a reference that covers little of a run
    cannot pass unnoticed.
    """
    from meeting_assistant.evaluation.references import label_at, language_at
    report: dict[str, Any] = {"clip_id": clip_id}

    if hypothesis.transcript_text is not None and reference.transcript_text is not None:
        report["asr"] = {
            "wer_raw": word_error_rate(
                reference.transcript_text, hypothesis.transcript_text
            ).as_dict(),
            "wer_romanized": romanized_word_error_rate(
                reference.transcript_text, hypothesis.transcript_text
            ).as_dict(),
            "cer_raw": character_error_rate(
                reference.transcript_text, hypothesis.transcript_text
            ).as_dict(),
            # Sensitivity of the headline number to filler words (decision D2).
            "wer_raw_no_fillers": word_error_rate(
                reference.transcript_text, hypothesis.transcript_text, strip_fillers=True
            ).as_dict(),
        }

    if hypothesis.turns is not None and reference.turns is not None:
        report["diarization"] = {
            **diarization_error_rate(reference.turns, hypothesis.turns).as_dict(),
            # The DISPLACE protocol (no collar, overlapping speech scored), so
            # the number is comparable with that challenge's published results.
            "no_collar": diarization_error_rate(
                reference.turns, hypothesis.turns, collar=0.0
            ).as_dict(),
        }

    if hypothesis.resolved_segments is not None and reference.language_spans is not None:
        pairs = [
            (truth, segment.get("language"))
            for segment in hypothesis.resolved_segments
            if (truth := language_at(segment["start"], segment["end"],
                                     reference.language_spans)) is not None
        ]
        report["language_id"] = {
            **classification_metrics(
                [truth for truth, _ in pairs], [str(guess) for _, guess in pairs]
            ).as_dict(),
            "segments_scored": len(pairs),
            "segments_total": len(hypothesis.resolved_segments),
        }

    if hypothesis.romanized_segments is not None and reference.language_spans is not None:
        # What a detector that ran *after* romanization would say: the reason
        # language ID runs first, measured rather than asserted.
        from meeting_assistant.language.detection import detect_language

        pairs = [
            (truth, detect_language(segment.get("text", "")))
            for segment in hypothesis.romanized_segments
            if (truth := language_at(segment["start"], segment["end"],
                                     reference.language_spans)) is not None
        ]
        if pairs:
            report["language_id_after_romanization"] = {
                **classification_metrics(
                    [truth for truth, _ in pairs], [str(guess) for _, guess in pairs]
                ).as_dict(),
                "segments_scored": len(pairs),
            }

    if hypothesis.resolved_segments:
        from meeting_assistant.align.alignment import UNKNOWN_SPEAKER

        spoken = sum(max(0.0, s["end"] - s["start"]) for s in hypothesis.resolved_segments)
        unattributed = sum(
            max(0.0, s["end"] - s["start"])
            for s in hypothesis.resolved_segments
            if s.get("speaker") == UNKNOWN_SPEAKER
        )
        report["attribution"] = {
            "unattributed_share": round(unattributed / spoken, 4) if spoken else 0.0,
            "unattributed_seconds": round(unattributed, 2),
        }

    if hypothesis.summary is not None and reference.summary_rubric is not None:
        report["summary_rubric"] = {
            **reference.summary_rubric,
            "mean": round(
                sum(reference.summary_rubric.values()) / len(reference.summary_rubric), 4
            ),
        }

    if hypothesis.summary is not None and reference.summary is not None:
        report["summary"] = summary_rouge(reference.summary, hypothesis.summary).as_dict()

    if hypothesis.action_items is not None and reference.action_items is not None:
        report["action_items"] = action_item_metrics(
            hypothesis.action_items, reference.action_items
        ).as_dict()

    if hypothesis.resolved_segments is not None and reference.turns is not None:
        merged = [
            {
                **segment,
                "true_speaker": label_at(segment["start"], segment["end"], reference.turns,
                                         "speaker"),
            }
            for segment in hypothesis.resolved_segments
        ]
        true_count = reference.true_speaker_count or len(
            {turn["speaker"] for turn in reference.turns}
        )
        report["registry"] = registry_summary_metrics(
            merged, true_speaker_count=true_count
        ).as_dict()

    if hypothesis.system_metrics is not None:
        report["system"] = dict(hypothesis.system_metrics)

    return report


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _aggregate_leaf(values: list[Any]) -> Any:
    """Mean of numeric values, element-wise merge of nested dicts, or the
    single agreed-on value for anything else -- ``None`` if clips disagree
    on a non-numeric field (there is no meaningful "average" of two
    different confusion-matrix label sets, for instance)."""
    present = [v for v in values if v is not None]
    if not present:
        return None
    if all(_is_number(v) for v in present):
        return round(sum(present) / len(present), 4)
    if all(isinstance(v, dict) for v in present):
        keys = {key for v in present for key in v}
        return {key: _aggregate_leaf([v.get(key) for v in present]) for key in sorted(keys)}
    if len({repr(v) for v in present}) == 1:
        return present[0]
    return None


def aggregate_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean of each metric family across every clip that reported it.

    A clip missing a family entirely (Ollama down for that run, a reference
    not yet labelled for that metric) is skipped for that family rather than
    counted as a zero, so one incomplete clip does not silently drag down an
    aggregate every other clip actually contributed to.

    This is a plain per-clip mean, not a confidence interval — bootstrap CIs
    over multiple *runs of the same configuration* belong to
    ``meeting_assistant.experiments.aggregate`` (a later phase), which
    compares configurations; this function aggregates across the clips of one
    evaluation pass.
    """
    # ``source`` (which run a clip was scored against) is provenance, not a metric.
    families = sorted(
        {key for report in reports for key in report if key not in ("clip_id", "source")}
    )
    aggregated: dict[str, Any] = {"num_clips": len(reports)}
    for family in families:
        aggregated[family] = _aggregate_leaf([report.get(family) for report in reports])
    intervals = {
        path: ci
        for path in HEADLINE_METRICS
        if (ci := bootstrap_ci([v for r in reports if _is_number(v := _get(r, path))]))
    }
    if intervals:
        aggregated["ci95"] = intervals
    return aggregated


# The numbers a results table reports, each with a bootstrap confidence interval.
HEADLINE_METRICS = (
    "asr.wer_raw.wer",
    "asr.wer_romanized.wer",
    "asr.cer_raw.cer",
    "asr.wer_raw_no_fillers.wer",
    "diarization.der",
    "diarization.no_collar.der",
    "registry.identity_accuracy",
    "language_id.accuracy",
    "language_id_after_romanization.accuracy",
    "attribution.unattributed_share",
    "summary.rougeL_f",
    "summary_rubric.mean",
    "action_items.f1",
    "system.realtime_factor",
)
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 0


def _get(report: dict[str, Any], path: str) -> Any:
    value: Any = report
    for key in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def bootstrap_ci(values: list[float], *, level: float = 0.95) -> list[float] | None:
    """Percentile bootstrap interval for the mean over clips, or ``None`` for
    fewer than two clips (no spread to resample). Resampling is seeded, so a
    report regenerated from the same runs gives the same interval."""
    if len(values) < 2:
        return None
    import random

    rng = random.Random(BOOTSTRAP_SEED)
    n = len(values)
    means = sorted(
        sum(rng.choice(values) for _ in range(n)) / n for _ in range(BOOTSTRAP_RESAMPLES)
    )
    tail = (1 - level) / 2
    low = means[int(tail * (BOOTSTRAP_RESAMPLES - 1))]
    high = means[int((1 - tail) * (BOOTSTRAP_RESAMPLES - 1))]
    return [round(low, 4), round(high, 4)]
