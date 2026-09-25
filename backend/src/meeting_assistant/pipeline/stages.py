"""The ten batch pipeline stages, and the constraints that hold between them.

Each stage has exactly one job and writes exactly one artifact (see
:data:`meeting_assistant.paths.ARTIFACTS`), which is why stage names and
artifact names are identical throughout this module. A :class:`StageSpec`
describes a stage declaratively — its name, what it needs on disk before it can
run, whether it needs credentials or a running LLM, and whether its failure
should abort the whole run — so the orchestrator in
:mod:`meeting_assistant.pipeline.batch` can reason about the pipeline as data
rather than as a hardcoded sequence of function calls.

**The ordering constraint that must never silently break.** Language tagging
(``tagged``) has to run before Hinglish normalization (``hinglish``), because
normalization rewrites the Devanagari script that tagging's classification
depends on — see :mod:`meeting_assistant.language.detection` for the full
explanation. This is not merely documented here: the ``hinglish`` stage
declares ``requires=("tagged",)``, so the orchestrator physically cannot run it
without a tagged artifact already on disk, regardless of what order anyone
lists the stages in.

**Hard versus soft stages.** Only ``transcript`` and ``aligned`` are hard —
without a transcript there is nothing to build on, and without speaker
attribution the rest of the pipeline has no meaningful structure to work with.
Every other stage is soft, including ``diarization``: a failed diarization
still leaves a usable (if entirely ``UNKNOWN``-attributed) transcript, and every
LLM-backed stage failing must never discard the — often much more
expensive — transcription and diarization work that already succeeded. A soft
stage's failure is recorded, not hidden, and stages that depend on its output
are then skipped rather than crashing on missing input.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from meeting_assistant import config
from meeting_assistant.align.alignment import (
    align_transcript,
    attribution_summary,
    merge_consecutive_same_speaker,
)
from meeting_assistant.analytics.meeting_metadata import generate_metadata
from meeting_assistant.analytics.speaker_statistics import compute_speaker_statistics
from meeting_assistant.errors import ArtifactError
from meeting_assistant.intel.action_items import extract_action_items
from meeting_assistant.intel.summarization import summarize_transcript
from meeting_assistant.io_utils import read_json, write_json
from meeting_assistant.language.detection import detect_language_for_segments, language_distribution
from meeting_assistant.language.normalize import normalize_transcript
from meeting_assistant.llm.client import OllamaClient
from meeting_assistant.logging_setup import get_logger
from meeting_assistant.paths import ARTIFACTS, RunPaths

log = get_logger(__name__)


@dataclass
class StageContext:
    """Everything a stage function needs, assembled once per run.

    ``whisper_model`` and ``diarization_pipeline`` are optional: in batch mode
    each is used exactly once, so the ``transcript`` and ``diarization`` stages
    simply load their own model on demand rather than the orchestrator
    pre-loading it. That is what keeps a model-loading failure isolated to its
    own (soft, for diarization) stage — anything eagerly loaded before the
    stage loop starts would fail outside any stage's try/except and abort the
    whole run regardless of that stage's declared hardness.

    Live capture (a later phase) is the case these fields exist for: there,
    the same model processes many chunks, so its orchestrator loads once,
    populates these fields, and every chunk's stage calls reuse them.
    """

    paths: RunPaths
    audio_path: Path | None
    num_speakers: int | None
    run_started_at: datetime
    whisper_model: Any = None
    diarization_pipeline: Any = None
    llm: OllamaClient | None = None


StageFn = Callable[[StageContext], dict[str, Any]]


@dataclass(frozen=True)
class StageSpec:
    """A pipeline stage, described declaratively.

    Args:
        name: identical to its artifact's key in :data:`meeting_assistant.paths.ARTIFACTS`.
        requires: artifact names that must already exist on disk before this
            stage may run. Enforced by the orchestrator before ``fn`` is ever
            called — a stage function can assume its inputs are present.
        hard: if this stage fails, the whole run aborts rather than continuing
            with the remaining stages skipped.
        needs_hf: requires a Hugging Face token to be configured.
        needs_ollama: requires a reachable Ollama server.
        fn: does the work, writes the artifact, and returns a small dict of
            counts to attach to that stage's manifest entry.
    """

    name: str
    requires: tuple[str, ...]
    fn: StageFn
    hard: bool = False
    needs_hf: bool = False
    needs_ollama: bool = False


# Artifacts a downstream text-consuming stage should read, in preference order.
# "hinglish" is preferred because it is the most readable form of the
# transcript; falling back to "tagged" or "merged" means those stages still
# produce a result even if normalization was skipped or failed, rather than
# refusing to run at all. This single chain is what keeps summarization,
# action-item extraction, speaker statistics and meeting metadata reading the
# same transcript as each other, rather than each stage guessing independently
# — which is exactly how the artifacts in the pre-rebuild prototype drifted
# apart into describing different recordings.
_INTEL_INPUT_CHAIN: tuple[str, ...] = ("hinglish", "tagged", "merged", "aligned")


def resolve_intel_input(paths: RunPaths) -> tuple[str, list[dict[str, Any]]]:
    """Pick the best available transcript artifact for a downstream stage.

    Returns:
        ``(artifact_name, segments)`` — the name is recorded in the caller's
        manifest counts, so it is always visible which input a given summary or
        statistic was actually computed from.

    Raises:
        ArtifactError: if none of the chain's artifacts exist.
    """
    for name in _INTEL_INPUT_CHAIN:
        if paths.has(name):
            return name, read_json(paths.artifact(name))
    raise ArtifactError(
        f"No transcript artifact available for {paths.run_id}; "
        f"expected one of {_INTEL_INPUT_CHAIN}"
    )


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------
def _stage_transcript(ctx: StageContext) -> dict[str, Any]:
    from meeting_assistant.asr.whisper_asr import load_model, transcribe_audio

    model = ctx.whisper_model or load_model()
    result = transcribe_audio(model, ctx.audio_path)
    write_json(ctx.paths.artifact("transcript"), result.segments)
    return result.as_manifest_dict()


def _stage_diarization(ctx: StageContext) -> dict[str, Any]:
    # Scoped to exactly what this stage needs, so a missing token produces a
    # clear, actionable message rather than a raw error from deep inside
    # pyannote or huggingface_hub -- and, because this runs inside the stage
    # function, the orchestrator's per-stage try/except catches it and treats
    # it as this one (soft) stage failing, not the whole run.
    config.validate_config(require_hf_token=True, require_ffmpeg=False, require_ollama=False)

    from meeting_assistant.diarize.pyannote_diarizer import diarize_audio, load_pipeline

    pipeline = ctx.diarization_pipeline or load_pipeline(config.HF_TOKEN)
    result = diarize_audio(pipeline, ctx.audio_path, num_speakers=ctx.num_speakers)
    write_json(ctx.paths.artifact("diarization"), result.segments)
    return result.as_manifest_dict()


def _stage_aligned(ctx: StageContext) -> dict[str, Any]:
    transcript_segments = read_json(ctx.paths.artifact("transcript"))
    # Diarization is soft; if it failed, align on an empty speaker list, which
    # yields an honestly all-UNKNOWN transcript rather than refusing to
    # produce anything at all.
    speaker_segments = (
        read_json(ctx.paths.artifact("diarization")) if ctx.paths.has("diarization") else []
    )

    aligned = align_transcript(transcript_segments, speaker_segments)
    write_json(ctx.paths.artifact("aligned"), aligned)
    return attribution_summary(aligned)


def _stage_merged(ctx: StageContext) -> dict[str, Any]:
    aligned = read_json(ctx.paths.artifact("aligned"))
    merged = merge_consecutive_same_speaker(aligned)
    write_json(ctx.paths.artifact("merged"), merged)
    return {"input_segments": len(aligned), "output_segments": len(merged)}


def _stage_tagged(ctx: StageContext) -> dict[str, Any]:
    merged = read_json(ctx.paths.artifact("merged"))
    tagged = detect_language_for_segments(merged)
    write_json(ctx.paths.artifact("tagged"), tagged)
    return {"segments": len(tagged), **language_distribution(tagged)}


def _stage_hinglish(ctx: StageContext) -> dict[str, Any]:
    config.validate_config(require_hf_token=False, require_ffmpeg=False, require_ollama=True)

    tagged = read_json(ctx.paths.artifact("tagged"))
    result = normalize_transcript(tagged, ctx.llm)
    write_json(ctx.paths.artifact("hinglish"), result.segments)
    return result.as_manifest_dict()


def _stage_summary(ctx: StageContext) -> dict[str, Any]:
    config.validate_config(require_hf_token=False, require_ffmpeg=False, require_ollama=True)

    input_name, segments = resolve_intel_input(ctx.paths)
    result = summarize_transcript(segments, ctx.llm)
    write_json(ctx.paths.artifact("summary"), result.as_dict())
    return {"input_artifact": input_name, **result.as_manifest_dict()}


def _stage_action_items(ctx: StageContext) -> dict[str, Any]:
    config.validate_config(require_hf_token=False, require_ffmpeg=False, require_ollama=True)

    input_name, segments = resolve_intel_input(ctx.paths)
    result = extract_action_items(segments, ctx.llm)
    write_json(ctx.paths.artifact("action_items"), result.as_dict())
    return {"input_artifact": input_name, **result.as_manifest_dict()}


def _stage_speaker_stats(ctx: StageContext) -> dict[str, Any]:
    input_name, segments = resolve_intel_input(ctx.paths)
    stats = compute_speaker_statistics(segments)
    write_json(ctx.paths.artifact("speaker_stats"), stats)
    return {"input_artifact": input_name, **stats["totals"]}


def _stage_metadata(ctx: StageContext) -> dict[str, Any]:
    input_name, segments = resolve_intel_input(ctx.paths)
    metadata = generate_metadata(
        segments,
        meeting_id=ctx.paths.run_id,
        date=ctx.run_started_at.strftime("%Y-%m-%d"),
        time=ctx.run_started_at.strftime("%H:%M:%S"),
    )
    write_json(ctx.paths.artifact("metadata"), metadata)
    return {"input_artifact": input_name, **metadata}


# ---------------------------------------------------------------------------
# The pipeline, as data
# ---------------------------------------------------------------------------
BATCH_STAGES: tuple[StageSpec, ...] = (
    StageSpec("transcript", requires=(), fn=_stage_transcript, hard=True),
    StageSpec("diarization", requires=(), fn=_stage_diarization, needs_hf=True),
    StageSpec("aligned", requires=("transcript",), fn=_stage_aligned, hard=True),
    StageSpec("merged", requires=("aligned",), fn=_stage_merged),
    StageSpec("tagged", requires=("merged",), fn=_stage_tagged),
    StageSpec("hinglish", requires=("tagged",), fn=_stage_hinglish, needs_ollama=True),
    StageSpec("summary", requires=(), fn=_stage_summary, needs_ollama=True),
    StageSpec("action_items", requires=(), fn=_stage_action_items, needs_ollama=True),
    StageSpec("speaker_stats", requires=(), fn=_stage_speaker_stats),
    StageSpec("metadata", requires=(), fn=_stage_metadata),
)

# The four downstream stages don't declare a hard `requires` on any single
# transcript artifact, because resolve_intel_input's fallback chain means any
# one of several artifacts satisfies them. What they truly require is "at
# least one transcript-shaped artifact exists," which resolve_intel_input
# itself enforces by raising ArtifactError — caught by the orchestrator like
# any other stage failure — rather than the declarative `requires` list.

STAGE_NAMES: tuple[str, ...] = tuple(spec.name for spec in BATCH_STAGES)
STAGES_BY_NAME: dict[str, StageSpec] = {spec.name: spec for spec in BATCH_STAGES}

assert STAGE_NAMES == tuple(ARTIFACTS.keys()), (
    "BATCH_STAGES must declare stages in exactly the same order as "
    "paths.ARTIFACTS, since stage name and artifact name are the same thing "
    "throughout this pipeline."
)
