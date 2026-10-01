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
            "execution": 0,
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
        "resumes",
        "consistency",
        "stages",
        "extra",
    }



# ---------------------------------------------------------------------------
# Executions: a resumed run's stages may come from more than one process
# ---------------------------------------------------------------------------
@pytest.fixture
def recording(tmp_path):
    path = tmp_path / "meeting.wav"
    path.write_bytes(b"original recording")
    return path


def _started(runs_dir, recording):
    paths = new_run("batch", recording.name, runs_dir=runs_dir)
    return RunManifest.start(paths, mode="batch", audio_path=str(recording))


def _add_resume(manifest, *, config_hash=None, git=None):
    """Attribute later stages to a hand-made execution record."""
    manifest.resumes.append(
        {
            "execution": len(manifest.resumes) + 1,
            "config_hash": config_hash or manifest.provenance_block["config_hash"],
            "git": git or {},
        }
    )
    manifest.current_execution = len(manifest.resumes)


def test_a_single_execution_run_is_consistent(runs_dir, recording):
    manifest = _started(runs_dir, recording)
    manifest.record_stage("transcript", STAGE_OK)
    assert manifest.consistency() == {"executions": [0], "config": True, "code": True}
    assert manifest.evaluation_ineligibility() is None


def test_resume_is_recorded_as_a_new_execution(runs_dir, recording):
    manifest = _started(runs_dir, recording)
    manifest.record_stage("transcript", STAGE_OK)

    resumed = RunManifest.load(manifest.paths)
    resumed.check_resumable()
    resumed.begin_execution()
    resumed.record_stage("aligned", STAGE_OK)

    data = read_json(manifest.paths.manifest_path)
    assert [r["execution"] for r in data["resumes"]] == [1]
    assert data["resumes"][0]["config_hash"] == data["provenance"]["config_hash"]
    assert {s["name"]: s["execution"] for s in data["stages"]} == {"transcript": 0, "aligned": 1}
    assert data["consistency"]["executions"] == [0, 1]


def test_a_run_with_no_stages_recaptures_its_own_provenance(runs_dir, recording):
    """The API creates a run and executes it later: nothing has been produced
    yet, so the run's provenance should describe that execution, not a resume."""
    manifest = _started(runs_dir, recording)
    manifest.provenance_block["git"] = {"commit": "stale", "dirty": False}
    original_input = manifest.provenance_block["input"]

    manifest.begin_execution()

    assert manifest.resumes == []
    assert manifest.current_execution == 0
    assert manifest.provenance_block["git"]["commit"] != "stale"
    assert manifest.provenance_block["input"] == original_input


def test_resume_under_a_different_config_is_refused(runs_dir, recording, monkeypatch):
    from meeting_assistant import config
    from meeting_assistant.errors import ProvenanceError

    manifest = _started(runs_dir, recording)
    manifest.record_stage("transcript", STAGE_OK)
    monkeypatch.setattr(config, "OLLAMA_MODEL", "llama3.1:8b")

    with pytest.raises(ProvenanceError, match="ollama_model"):
        RunManifest.load(manifest.paths).check_resumable()


def test_mixed_config_can_be_allowed_but_marks_the_run_inconsistent(
    runs_dir, recording, monkeypatch
):
    from meeting_assistant import config

    manifest = _started(runs_dir, recording)
    manifest.record_stage("transcript", STAGE_OK)
    monkeypatch.setattr(config, "OLLAMA_MODEL", "llama3.1:8b")

    resumed = RunManifest.load(manifest.paths)
    resumed.check_resumable(allow_mixed_config=True)
    resumed.begin_execution(allow_mixed_config=True)
    resumed.record_stage("summary", STAGE_OK)

    assert resumed.resumes[0]["allow_mixed_config"] is True
    assert resumed.consistency()["config"] is False
    assert "different configurations" in resumed.evaluation_ineligibility()


def test_forcing_every_earlier_stage_away_makes_a_config_change_acceptable(
    runs_dir, recording, monkeypatch
):
    """--force transcript deletes everything, so nothing is left to mix with."""
    from meeting_assistant import config

    manifest = _started(runs_dir, recording)
    manifest.record_stage("transcript", STAGE_OK)
    monkeypatch.setattr(config, "OLLAMA_MODEL", "llama3.1:8b")

    RunManifest.load(manifest.paths).check_resumable(force_stage="transcript")


def test_resume_against_a_different_recording_is_always_refused(runs_dir, recording):
    from meeting_assistant.errors import ProvenanceError

    manifest = _started(runs_dir, recording)
    manifest.record_stage("transcript", STAGE_OK)
    recording.write_bytes(b"a different meeting under the same name")

    with pytest.raises(ProvenanceError, match="sha256"):
        RunManifest.load(manifest.paths).check_resumable(allow_mixed_config=True)


def test_executions_from_different_commits_are_not_code_consistent(runs_dir, recording):
    manifest = _started(runs_dir, recording)
    manifest.provenance_block["git"] = {"commit": "aaa", "dirty": False}
    manifest.record_stage("transcript", STAGE_OK)
    _add_resume(manifest, git={"commit": "bbb", "dirty": False})
    manifest.record_stage("aligned", STAGE_OK)

    assert manifest.consistency()["code"] is False
    assert "different or uncommitted code" in manifest.evaluation_ineligibility()


def test_executions_from_a_dirty_tree_are_not_code_consistent(runs_dir, recording):
    """Same commit hash, but uncommitted edits: the code that ran is unknown."""
    manifest = _started(runs_dir, recording)
    manifest.provenance_block["git"] = {"commit": "aaa", "dirty": True}
    manifest.record_stage("transcript", STAGE_OK)
    _add_resume(manifest, git={"commit": "aaa", "dirty": True})
    manifest.record_stage("aligned", STAGE_OK)

    assert manifest.consistency()["code"] is False


def test_executions_on_one_clean_commit_are_consistent(runs_dir, recording):
    manifest = _started(runs_dir, recording)
    manifest.provenance_block["git"] = {"commit": "aaa", "dirty": False}
    manifest.record_stage("transcript", STAGE_OK)
    _add_resume(manifest, git={"commit": "aaa", "dirty": False})
    manifest.record_stage("aligned", STAGE_OK)

    assert manifest.consistency() == {"executions": [0, 1], "config": True, "code": True}


def test_legacy_manifest_without_execution_fields_loads(runs_dir, recording):
    from meeting_assistant.io_utils import write_json

    manifest = _started(runs_dir, recording)
    manifest.record_stage("transcript", STAGE_OK)
    data = read_json(manifest.paths.manifest_path)
    for key in ("resumes", "consistency"):
        data.pop(key)
    for stage in data["stages"]:
        stage.pop("execution")
    write_json(manifest.paths.manifest_path, data)

    loaded = RunManifest.load(manifest.paths)
    assert loaded.resumes == []
    assert loaded.consistency() == {"executions": [0], "config": True, "code": True}
