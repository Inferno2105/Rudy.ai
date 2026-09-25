"""Tests for the stage declarations and the downstream-input fallback chain.

The stage functions themselves (``_stage_transcript``, ``_stage_diarization``,
...) need real models or a real LLM and are exercised by the batch
orchestrator's own integration path, not unit-tested individually here. What
is unit-testable without any of that is the pipeline's *shape*: which stages
exist, what they require, which are hard, and how a downstream stage picks its
input when an earlier optional stage did not run.
"""

from __future__ import annotations

import pytest

from meeting_assistant.errors import ArtifactError
from meeting_assistant.io_utils import write_json
from meeting_assistant.paths import ARTIFACTS, new_run
from meeting_assistant.pipeline.stages import (
    BATCH_STAGES,
    STAGE_NAMES,
    STAGES_BY_NAME,
    resolve_intel_input,
)


def test_stage_names_match_the_artifact_registry_exactly():
    """Stage name and artifact name are the same thing throughout this pipeline."""
    assert STAGE_NAMES == tuple(ARTIFACTS.keys())


def test_exactly_two_stages_are_hard():
    """transcript and aligned: without either, nothing downstream is meaningful."""
    hard = {spec.name for spec in BATCH_STAGES if spec.hard}
    assert hard == {"transcript", "aligned"}


def test_diarization_is_soft():
    """A failed diarization must still leave a usable, all-UNKNOWN transcript."""
    assert STAGES_BY_NAME["diarization"].hard is False


def test_every_llm_backed_stage_is_soft():
    """An Ollama outage must not be able to abort the whole run."""
    llm_stages = [spec for spec in BATCH_STAGES if spec.needs_ollama]
    assert llm_stages  # sanity: there should be some
    assert all(not spec.hard for spec in llm_stages)


def test_hinglish_requires_tagged():
    """The ordering constraint enforced structurally, not just by list order."""
    assert STAGES_BY_NAME["hinglish"].requires == ("tagged",)


def test_only_diarization_and_hinglish_declare_credential_or_server_needs():
    needs_hf = {spec.name for spec in BATCH_STAGES if spec.needs_hf}
    needs_ollama = {spec.name for spec in BATCH_STAGES if spec.needs_ollama}
    assert needs_hf == {"diarization"}
    assert needs_ollama == {"hinglish", "summary", "action_items"}


def test_stages_by_name_covers_every_stage():
    assert set(STAGES_BY_NAME) == set(STAGE_NAMES)


# --------------------------------------------------------------------------
# resolve_intel_input
# --------------------------------------------------------------------------
def test_prefers_hinglish_when_present(runs_dir):
    paths = new_run("batch", "a.wav", runs_dir=runs_dir)
    write_json(paths.artifact("merged"), [{"text": "merged"}])
    write_json(paths.artifact("tagged"), [{"text": "tagged"}])
    write_json(paths.artifact("hinglish"), [{"text": "hinglish"}])

    name, segments = resolve_intel_input(paths)
    assert name == "hinglish"
    assert segments[0]["text"] == "hinglish"


def test_falls_back_to_tagged_when_hinglish_is_absent(runs_dir):
    """The real scenario this fallback exists for: normalization failed (soft),
    but tagging succeeded, so downstream stages should still produce a result."""
    paths = new_run("batch", "a.wav", runs_dir=runs_dir)
    write_json(paths.artifact("merged"), [{"text": "merged"}])
    write_json(paths.artifact("tagged"), [{"text": "tagged"}])

    name, segments = resolve_intel_input(paths)
    assert name == "tagged"
    assert segments[0]["text"] == "tagged"


def test_falls_back_to_merged_when_only_merged_exists(runs_dir):
    paths = new_run("batch", "a.wav", runs_dir=runs_dir)
    write_json(paths.artifact("merged"), [{"text": "merged"}])

    name, segments = resolve_intel_input(paths)
    assert name == "merged"


def test_falls_back_to_aligned_as_the_last_resort(runs_dir):
    paths = new_run("batch", "a.wav", runs_dir=runs_dir)
    write_json(paths.artifact("aligned"), [{"text": "aligned"}])

    name, segments = resolve_intel_input(paths)
    assert name == "aligned"


def test_raises_when_nothing_in_the_chain_exists(runs_dir):
    paths = new_run("batch", "a.wav", runs_dir=runs_dir)
    with pytest.raises(ArtifactError, match="No transcript artifact"):
        resolve_intel_input(paths)


def test_never_falls_back_past_aligned_to_diarization_or_transcript(runs_dir):
    """diarization and transcript are not transcript-shaped for this purpose --
    transcript has no speaker field and diarization has no text field."""
    paths = new_run("batch", "a.wav", runs_dir=runs_dir)
    write_json(paths.artifact("transcript"), [{"text": "raw"}])
    write_json(paths.artifact("diarization"), [{"speaker": "SPEAKER_00"}])

    with pytest.raises(ArtifactError):
        resolve_intel_input(paths)
