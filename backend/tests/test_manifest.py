"""Tests for the run manifest.

Every figure this project ever reports has to trace back through a manifest,
so its serialization round-trip and its status bookkeeping are worth testing
directly, independent of the orchestrator that drives them.
"""

from __future__ import annotations

import pytest

from meeting_assistant.errors import ArtifactError
from meeting_assistant.io_utils import read_json
from meeting_assistant.paths import new_run
from meeting_assistant.pipeline.manifest import (
    STAGE_FAILED,
    STAGE_OK,
    STAGE_SKIPPED,
    STATUS_PARTIAL,
    RunManifest,
)


def _paths(runs_dir):
    return new_run("batch", "meeting.wav", runs_dir=runs_dir)


def test_start_writes_a_manifest_immediately(runs_dir):
    """Even a run that crashes before its first stage must leave a record."""
    paths = _paths(runs_dir)
    RunManifest.start(paths, mode="batch", audio_path="data/audio/meeting.wav")
    assert paths.manifest_path.exists()


def test_start_captures_provenance(runs_dir):
    paths = _paths(runs_dir)
    manifest = RunManifest.start(paths, mode="batch")
    assert "git" in manifest.provenance_block
    assert "config_hash" in manifest.provenance_block


def test_start_defaults_to_real_audio_origin(runs_dir):
    manifest = RunManifest.start(_paths(runs_dir), mode="batch")
    assert manifest.data_origin == "real_audio"


def test_synthetic_origin_can_be_declared(runs_dir):
    manifest = RunManifest.start(_paths(runs_dir), mode="batch", data_origin="synthetic")
    assert manifest.data_origin == "synthetic"


def test_status_starts_partial(runs_dir):
    manifest = RunManifest.start(_paths(runs_dir), mode="batch")
    assert manifest.status == STATUS_PARTIAL


def test_record_stage_saves_immediately(runs_dir):
    paths = _paths(runs_dir)
    manifest = RunManifest.start(paths, mode="batch")
    manifest.record_stage("transcript", STAGE_OK, seconds=1.5, counts={"segments": 3})

    reloaded = read_json(paths.manifest_path)
    assert reloaded["stages"] == [
        {
            "name": "transcript",
            "status": "ok",
            "seconds": 1.5,
            "outputs": [],
            "counts": {"segments": 3},
            "error": None,
        }
    ]


def test_record_stage_replaces_a_prior_entry_for_the_same_name(runs_dir):
    """A --force re-run must not leave the stale attempt's entry behind."""
    manifest = RunManifest.start(_paths(runs_dir), mode="batch")
    manifest.record_stage("tagged", STAGE_FAILED, error="boom")
    manifest.record_stage("tagged", STAGE_OK, counts={"segments": 5})

    assert len(manifest.stages) == 1
    assert manifest.stages[0]["status"] == "ok"


def test_stage_status_returns_none_for_a_stage_never_run(runs_dir):
    manifest = RunManifest.start(_paths(runs_dir), mode="batch")
    assert manifest.stage_status("hinglish") is None


def test_stage_status_reflects_the_latest_recording(runs_dir):
    manifest = RunManifest.start(_paths(runs_dir), mode="batch")
    manifest.record_stage("tagged", STAGE_FAILED, error="boom")
    manifest.record_stage("tagged", STAGE_OK)
    assert manifest.stage_status("tagged") == STAGE_OK


def test_drop_stage_removes_the_entry_without_saving(runs_dir):
    paths = _paths(runs_dir)
    manifest = RunManifest.start(paths, mode="batch")
    manifest.record_stage("metadata", STAGE_OK)
    manifest.drop_stage("metadata")

    assert manifest.stage_status("metadata") is None
    # Not saved yet -- the caller (e.g. --force) is expected to call save()
    # itself once all the invalidation for a run is complete.
    reloaded = read_json(paths.manifest_path)
    assert any(s["name"] == "metadata" for s in reloaded["stages"])


def test_set_status_records_a_finish_time(runs_dir):
    manifest = RunManifest.start(_paths(runs_dir), mode="batch")
    manifest.set_status("completed")
    assert manifest.status == "completed"
    assert manifest.provenance_block.get("finished_at")


def test_set_extra_is_persisted(runs_dir):
    paths = _paths(runs_dir)
    manifest = RunManifest.start(paths, mode="batch")
    manifest.set_extra("live_stats", {"chunks_recorded": 4})

    reloaded = read_json(paths.manifest_path)
    assert reloaded["extra"]["live_stats"]["chunks_recorded"] == 4


def test_load_reopens_an_existing_manifest_with_its_stage_history(runs_dir):
    paths = _paths(runs_dir)
    original = RunManifest.start(paths, mode="batch", audio_path="x.wav")
    original.record_stage("transcript", STAGE_OK, counts={"segments": 2})
    original.set_status("partial")

    reopened = RunManifest.load(paths)
    assert reopened.run_id == original.run_id
    assert reopened.status == "partial"
    assert reopened.stage_status("transcript") == STAGE_OK
    assert reopened.provenance_block["config_hash"] == original.provenance_block["config_hash"]


def test_load_raises_for_a_run_with_no_manifest(runs_dir):
    paths = _paths(runs_dir)
    # A run directory exists (new_run creates it), but start() was never called.
    with pytest.raises(ArtifactError, match="no manifest"):
        RunManifest.load(paths)


def test_as_dict_matches_the_documented_shape(runs_dir):
    manifest = RunManifest.start(_paths(runs_dir), mode="batch")
    manifest.record_stage("transcript", STAGE_SKIPPED, error="missing input")
    manifest.set_status("failed")

    data = manifest.as_dict()
    assert set(data.keys()) == {
        "run_id",
        "mode",
        "status",
        "data_origin",
        "provenance",
        "stages",
        "extra",
    }
