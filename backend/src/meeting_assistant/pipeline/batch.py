"""Batch orchestrator: run every stage over one audio file into one run directory.

This is the first place in the project's history where the full chain —
transcription, diarization, alignment, language tagging, Hinglish
normalization, summarization, action-item extraction, and statistics — runs as
a single reproducible unit against real audio, writing into an isolated run
directory that nothing else can silently overwrite (see
:mod:`meeting_assistant.paths`).

Stages run in :data:`meeting_assistant.pipeline.stages.BATCH_STAGES` order.
Failure handling follows each stage's declared hardness: a hard stage's
failure aborts the run immediately (``status: "failed"``); a soft stage's
failure is recorded and the run continues, skipping whatever depends on the
missing output (``status`` ends as ``"partial"`` unless everything selected
happened to succeed).
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from meeting_assistant import config
from meeting_assistant.errors import ArtifactError
from meeting_assistant.llm.client import OllamaClient
from meeting_assistant.logging_setup import attach_run_log, detach_run_log, get_logger
from meeting_assistant.paths import ARTIFACTS, RunPaths, new_run, open_run
from meeting_assistant.pipeline.manifest import (
    STAGE_FAILED,
    STAGE_OK,
    STAGE_SKIPPED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PARTIAL,
    RunManifest,
)
from meeting_assistant.pipeline.stages import BATCH_STAGES, STAGES_BY_NAME, StageContext, StageSpec

log = get_logger(__name__)


@dataclass
class BatchOptions:
    """User-facing knobs for one batch invocation."""

    num_speakers: int | None = None
    resume_run_id: str | None = None
    force_stage: str | None = None
    only_stage: str | None = None
    skip_stages: tuple[str, ...] = ()
    # Resume even if the output-affecting configuration changed since the
    # run's earlier stages. Marks the run inconsistent; debugging only.
    allow_mixed_config: bool = False


def _validate_stage_names(names: str | Iterable[str]) -> None:
    candidates = [names] if isinstance(names, str) else list(names)
    unknown = [n for n in candidates if n not in STAGES_BY_NAME]
    if unknown:
        raise ValueError(f"Unknown stage(s) {unknown}. Known: {', '.join(STAGES_BY_NAME)}")


def _select_stages(opts: BatchOptions) -> list[StageSpec]:
    """Which stages this invocation should consider, in pipeline order.

    ``--only`` and ``--skip`` are mutually exclusive in intent (one names what
    to run, the other what to exclude), so ``--only`` simply wins if both are
    given rather than trying to combine them.
    """
    if opts.only_stage:
        _validate_stage_names(opts.only_stage)
        return [STAGES_BY_NAME[opts.only_stage]]

    if opts.skip_stages:
        _validate_stage_names(opts.skip_stages)
    return [spec for spec in BATCH_STAGES if spec.name not in opts.skip_stages]


def _invalidate_from(paths: RunPaths, manifest: RunManifest, start_stage: str) -> None:
    """Delete a stage's artifact and every later stage's, for ``--force``.

    Also drops their manifest entries. Leaving a stale "ok" record next to a
    deleted artifact would let the manifest and the filesystem disagree about
    whether a result exists — precisely the kind of drift this project's
    run-isolation design exists to make impossible.
    """
    _validate_stage_names(start_stage)
    names = list(ARTIFACTS.keys())
    for name in names[names.index(start_stage) :]:
        artifact_path = paths.artifact(name)
        if artifact_path.exists():
            artifact_path.unlink()
            log.info("Deleted stale artifact for --force %s: %s", start_stage, name)
        manifest.drop_stage(name)
    manifest.save()


def _already_done(manifest: RunManifest, paths: RunPaths, name: str) -> bool:
    return manifest.stage_status(name) == STAGE_OK and paths.has(name)


def _build_context(paths: RunPaths, audio_path: Path | None, opts: BatchOptions) -> StageContext:
    """Assemble the context stages run against.

    Deliberately does **not** pre-load the Whisper model or the diarization
    pipeline here. Loading either is expensive enough to fail on its own
    (a bad token, an unreachable model repo), and in batch mode each is used
    exactly once — so the ``transcript`` and ``diarization`` stages simply
    load what they need themselves, which keeps a load failure inside that
    one stage's try/except rather than aborting the run before the stage loop
    even starts. ``OllamaClient`` is safe to construct unconditionally: it
    makes no network call until a stage actually asks it to generate
    something.
    """
    return StageContext(
        paths=paths,
        audio_path=audio_path,
        num_speakers=opts.num_speakers,
        run_started_at=datetime.now(),
        llm=OllamaClient(),
    )


def _final_status(manifest: RunManifest, selected: list[StageSpec], aborted: bool) -> str:
    if aborted:
        return STATUS_FAILED
    statuses = {manifest.stage_status(spec.name) for spec in selected}
    return STATUS_COMPLETED if statuses == {STAGE_OK} else STATUS_PARTIAL


def create_batch_run(audio_path: str | Path) -> RunPaths:
    """Create a run directory and its initial manifest, without running anything.

    Split out so a caller that must hand back a ``run_id`` before the
    (minutes-long) work starts -- the HTTP API -- can create the run, return
    immediately, and execute it later via ``run_batch`` with ``resume_run_id``:
    a resume with no completed stages runs every stage, so there is no second
    code path to keep in step with this one.

    Raises:
        ArtifactError: the audio file does not exist.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise ArtifactError(f"Audio file not found: {audio_path}")
    paths = new_run("batch", audio_path)
    RunManifest.start(paths, mode="batch", audio_path=str(audio_path))
    return paths


def run_batch(audio_path: str | Path | None, opts: BatchOptions | None = None) -> RunPaths:
    """Run the batch pipeline over one audio file, or resume an existing run.

    Args:
        audio_path: source recording. May be ``None`` only when
            ``opts.resume_run_id`` is set and the run's manifest already
            recorded the original path.
        opts: see :class:`BatchOptions`.

    Returns:
        The run's :class:`~meeting_assistant.paths.RunPaths`. Check
        ``paths.manifest_path`` (or ``meeting-assistant runs --show <run_id>``)
        for the final status — this function does not raise merely because a
        soft stage failed.

    Raises:
        ArtifactError: the audio file (for a new run) or the run (for
            ``--resume``) does not exist.
        ProvenanceError: a resume would mix configurations or recordings
            (see :meth:`RunManifest.check_resumable`). Raised before the run
            is touched. A missing prerequisite for one
            *stage* (a Hugging Face token, an unreachable Ollama server) does
            **not** raise out of this function — it is recorded as that
            stage's own failure in the manifest, so it cannot abort stages
            that do not need it.
    """
    opts = opts or BatchOptions()
    audio_path = Path(audio_path) if audio_path is not None else None

    if opts.resume_run_id:
        paths = open_run(opts.resume_run_id)
        manifest = RunManifest.load(paths)
        if audio_path is None:
            recorded = (manifest.provenance_block.get("input") or {}).get("path")
            audio_path = Path(recorded) if recorded else None
        manifest.check_resumable(
            audio_path=audio_path,
            force_stage=opts.force_stage,
            allow_mixed_config=opts.allow_mixed_config,
        )
    else:
        if audio_path is None:
            raise ArtifactError("Audio file not found: None")
        paths = create_batch_run(audio_path)
        manifest = RunManifest.load(paths)

    log.info("Run %s (%s)", paths.run_id, "resumed" if opts.resume_run_id else "started")
    log_handler = attach_run_log(paths.log_path)
    aborted = False

    try:
        selected = _select_stages(opts)

        if opts.force_stage:
            _invalidate_from(paths, manifest, opts.force_stage)

        to_run = [
            spec
            for spec in selected
            if not (opts.resume_run_id and _already_done(manifest, paths, spec.name))
        ]

        if not to_run:
            log.info("Nothing to do: every selected stage is already complete.")
        else:
            if opts.resume_run_id:
                manifest.begin_execution(allow_mixed_config=opts.allow_mixed_config)
                if manifest.current_execution:
                    log.info("Resume recorded as execution %d", manifest.current_execution)

            # A courtesy warning, not a gate: reports what is likely to fail
            # without aborting stages that do not need it. Each individual
            # stage that does need a credential or a server performs its own
            # scoped, raising check (see meeting_assistant.pipeline.stages) at
            # the point it actually needs it, so e.g. an unreachable Ollama
            # server only fails the LLM-backed stages and never prevents
            # transcription and diarization from running and being saved.
            for problem in config.list_problems(
                require_hf_token=any(s.needs_hf for s in to_run),
                require_ffmpeg=False,
                require_ollama=any(s.needs_ollama for s in to_run),
            ):
                log.warning("Preflight: %s", problem)

            ctx = _build_context(paths, audio_path, opts)

            for stage in to_run:
                missing = [name for name in stage.requires if not paths.has(name)]
                if missing:
                    log.warning("Skipping %s: missing required input %s", stage.name, missing)
                    manifest.record_stage(
                        stage.name, STAGE_SKIPPED, error=f"missing required input: {missing}"
                    )
                    continue

                log.info("Running stage: %s", stage.name)
                started = time.perf_counter()
                try:
                    counts = stage.fn(ctx)
                except Exception as exc:  # noqa: BLE001 -- a stage's own failure
                    # is caught here so it can be recorded and classified as
                    # soft/hard, rather than propagating and abandoning every
                    # already-successful stage's work along with it.
                    elapsed = time.perf_counter() - started
                    log.exception("Stage %s failed after %.1fs", stage.name, elapsed)
                    manifest.record_stage(
                        stage.name, STAGE_FAILED, seconds=elapsed, error=str(exc)
                    )
                    if stage.hard:
                        aborted = True
                        break
                else:
                    elapsed = time.perf_counter() - started
                    manifest.record_stage(
                        stage.name,
                        STAGE_OK,
                        seconds=elapsed,
                        outputs=[str(paths.artifact(stage.name))],
                        counts=counts,
                    )
                    log.info("Completed stage %s in %.1fs", stage.name, elapsed)

        manifest.set_status(_final_status(manifest, selected, aborted))
        log.info("Run %s finished: %s", paths.run_id, manifest.status)

    finally:
        detach_run_log(log_handler)

    return paths
