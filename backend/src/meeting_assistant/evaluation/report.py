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
    languages: list[str] | None = None
    summary: str | None = None
    action_items: list[dict[str, Any]] | None = None
    resolved_segments: list[dict[str, Any]] | None = None
    system_metrics: dict[str, Any] | None = None


@dataclass
class ClipReference:
    """Ground truth for one evaluation clip. Every field is optional for the
    same reason as :class:`ClipHypothesis` — a clip need only carry the
    references for the metric families it is meant to exercise."""

    transcript_text: str | None = None
    turns: list[dict[str, Any]] | None = None
    languages: list[str] | None = None
    summary: str | None = None
    action_items: list[dict[str, Any]] | None = None
    true_speakers: list[str] | None = None
    true_speaker_count: int | None = None


def generate_clip_report(
    clip_id: str, hypothesis: ClipHypothesis, reference: ClipReference
) -> dict[str, Any]:
    """One clip's full metric report, as a plain JSON-serializable dict.

    ``registry`` pairs ``hypothesis.resolved_segments`` with
    ``reference.true_speakers`` positionally (segment *i*'s true speaker is
    ``true_speakers[i]``), so the two must already be the same length and
    order — the reference labelling protocol is expected to walk the run's
    own stitched transcript and label each segment in place, not describe
    speakers independently.
    """
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
        }

    if hypothesis.turns is not None and reference.turns is not None:
        report["diarization"] = diarization_error_rate(reference.turns, hypothesis.turns).as_dict()

    if hypothesis.languages is not None and reference.languages is not None:
        report["language_id"] = classification_metrics(
            reference.languages, hypothesis.languages
        ).as_dict()

    if hypothesis.summary is not None and reference.summary is not None:
        report["summary"] = summary_rouge(reference.summary, hypothesis.summary).as_dict()

    if hypothesis.action_items is not None and reference.action_items is not None:
        report["action_items"] = action_item_metrics(
            hypothesis.action_items, reference.action_items
        ).as_dict()

    if hypothesis.resolved_segments is not None and reference.true_speakers is not None:
        merged = [
            {**segment, "true_speaker": true}
            for segment, true in zip(
                hypothesis.resolved_segments, reference.true_speakers, strict=True
            )
        ]
        report["registry"] = registry_summary_metrics(
            merged, true_speaker_count=reference.true_speaker_count
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
    families = sorted({key for report in reports for key in report if key != "clip_id"})
    aggregated: dict[str, Any] = {"num_clips": len(reports)}
    for family in families:
        aggregated[family] = _aggregate_leaf([report.get(family) for report in reports])
    return aggregated
