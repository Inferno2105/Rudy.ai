"""The evaluation report served by ``GET /api/eval/report``.

Mirrors what :mod:`meeting_assistant.evaluation.report` and ``meeting-assistant
eval`` write to ``data/eval/reports/latest.json``. Every metric family is
optional (a clip reports only the families it has references for), and every
model allows extra fields so a metric added to the harness later reaches the
UI's "raw" view before the schema catches up -- but the named fields are what
the dashboard renders, so they are typed.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class WordErrors(_Open):
    wer: float | None = None
    substitutions: float | None = None
    deletions: float | None = None
    insertions: float | None = None
    hits: float | None = None
    reference_words: float | None = None


class CharErrors(_Open):
    cer: float | None = None
    reference_chars: float | None = None


class AsrMetrics(_Open):
    wer_raw: WordErrors | None = None
    wer_romanized: WordErrors | None = None
    cer_raw: CharErrors | None = None
    wer_raw_no_fillers: WordErrors | None = Field(
        default=None, description="WER with filler words removed from both sides (sensitivity)"
    )


class DiarizationMetrics(_Open):
    der: float | None = None
    confusion: float | None = None
    missed_detection: float | None = None
    false_alarm: float | None = None
    total: float | None = None
    collar: float | None = None
    no_collar: DiarizationMetrics | None = Field(
        default=None,
        description="The same DER with no collar and overlapping speech scored "
        "(the DISPLACE protocol), comparable with published results",
    )


class LanguageIdMetrics(_Open):
    accuracy: float | None = None
    per_class: dict[str, dict[str, float | None]] | None = None
    confusion: Any = None
    labels: list[str] | None = None


class RougeMetrics(_Open):
    rouge1_f: float | None = None
    rouge2_f: float | None = None
    rougeL_f: float | None = None  # noqa: N815 -- the harness's own key
    rouge1_precision: float | None = None
    rouge1_recall: float | None = None


class ActionItemMetrics(_Open):
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    matched: float | None = None
    predicted_count: float | None = None
    reference_count: float | None = None
    deadline_accuracy: float | None = None


class RegistryMetrics(_Open):
    identity_accuracy: float | None = None
    predicted_speaker_count: float | None = None
    true_speaker_count: float | None = None
    unresolved_rate: float | None = None
    mean_match_similarity: float | None = None


class ClipSource(_Open):
    """Which run a clip was scored against -- what makes its numbers traceable."""

    run_id: str
    git_commit: str | None = None
    git_dirty: bool | None = None
    config_hash: str | None = None
    data_origin: str | None = Field(
        default=None,
        description='"real_audio" or "synthetic" (generated speech); absent in older reports',
    )
    dataset: str | None = Field(
        default=None,
        description='The set the clip is reported in: "recorded", "synthetic", or a '
        "published corpus such as displace2023-dev",
    )
    condition: str | None = Field(
        default=None, description="Recording condition from the clip's meta.json"
    )


class Attribution(_Open):
    unattributed_share: float | None = Field(
        default=None, description="Share of transcribed speech time left without a speaker"
    )
    unattributed_seconds: float | None = None


class SummaryRubric(_Open):
    faithfulness: float | None = None
    coverage: float | None = None
    no_invention: float | None = None
    mean: float | None = None


class MetricFamilies(_Open):
    asr: AsrMetrics | None = None
    diarization: DiarizationMetrics | None = None
    language_id: LanguageIdMetrics | None = None
    summary: RougeMetrics | None = None
    action_items: ActionItemMetrics | None = None
    registry: RegistryMetrics | None = None
    system: dict[str, Any] | None = None
    language_id_after_romanization: LanguageIdMetrics | None = Field(
        default=None,
        description="Language ID re-run on the romanized text: evidence for running it first",
    )
    attribution: Attribution | None = None
    summary_rubric: SummaryRubric | None = Field(
        default=None, description="Human rating of the summary, 1-3 per criterion"
    )


class ClipReport(MetricFamilies):
    clip_id: str
    source: ClipSource | None = Field(
        default=None, description="Absent only in reports written before sources were recorded"
    )


class AggregateReport(MetricFamilies):
    num_clips: int
    ci95: dict[str, list[float]] | None = Field(
        default=None,
        description="Percentile bootstrap 95% interval of the mean over clips, per headline "
        "metric (dotted path, e.g. asr.wer_raw.wer)",
    )


class EvalReport(_Open):
    generated_at: str | None = None
    git: dict[str, Any] | None = Field(default=None, description="Code state at generation")
    config_hashes: list[str] = Field(
        default_factory=list,
        description="Distinct config hashes across the scored runs; more than one means the "
        "aggregate mixes configurations",
    )
    clips: list[ClipReport]
    aggregate: AggregateReport = Field(
        description="Means over this project's own recordings"
    )
    aggregate_synthetic: AggregateReport | None = Field(
        default=None,
        description="Means over synthetic (generated-speech) clips, reported separately",
    )
    aggregate_external: dict[str, AggregateReport] = Field(
        default_factory=dict,
        description="Means over each published corpus (e.g. displace2023-dev), reported apart",
    )
    aggregate_by_condition: dict[str, dict[str, AggregateReport]] = Field(
        default_factory=dict,
        description="Each set's means again by recording condition",
    )
