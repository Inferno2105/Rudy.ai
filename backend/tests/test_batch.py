"""Tests for the batch orchestrator, with every stage faked.

No model, no Ollama server, no real audio decoding. The stage functions
themselves need real infrastructure and are exercised by the batch
orchestrator's real end-to-end run on genuine audio (verified manually against
``data/audio/test_hindi.wav`` — see the phase's commit message); what belongs
in the default, hermetic test suite is the orchestration logic around those
stages: ordering, failure classification, resume, and force-invalidation.

Fake stages are built from the *real* artifact names (``transcript``,
``tagged``, ...) rather than made-up ones, because :meth:`RunPaths.artifact`
only resolves names in the real registry -- which is itself the behaviour
under test in :mod:`test_paths`, so reusing it here keeps these tests honest
about what a real stage's artifact-writing looks like.
"""

from __future__ import annotations

import pytest

import meeting_assistant.pipeline.batch as batch_mod
from meeting_assistant.errors import ArtifactError
from meeting_assistant.io_utils import read_json, write_json
from meeting_assistant.pipeline.batch import BatchOptions, run_batch
from meeting_assistant.pipeline.stages import StageSpec


def _stub(name, *, requires=(), hard=False, needs_ollama=False, needs_hf=False, fails=False):
    def fn(ctx):
        if fails:
            raise RuntimeError(f"{name} failed on purpose")
        write_json(ctx.paths.artifact(name), {"stub": name})
        return {"stub": name}

    return StageSpec(
        name=name, requires=requires, fn=fn, hard=hard, needs_ollama=needs_ollama, needs_hf=needs_hf
    )


@pytest.fixture
def audio_file(tmp_path):
    path = tmp_path / "meeting.wav"
    path.write_bytes(b"not-real-audio")
    return path


@pytest.fixture
def patch_stages(monkeypatch):
    """Replace the real pipeline with a small set of fake stages.

    Returns a function so each test can install exactly the stage set it needs.
    """

    def install(specs: tuple[StageSpec, ...]):
        by_name = {spec.name: spec for spec in specs}
        monkeypatch.setattr(batch_mod, "BATCH_STAGES", specs)
        monkeypatch.setattr(batch_mod, "STAGES_BY_NAME", by_name)
        return specs

    return install


def _three_stage_chain(**overrides):
    """transcript (hard) -> aligned (hard) -> tagged, the minimal realistic shape."""
    return (
        _stub("transcript", hard=True, **overrides.get("transcript", {})),
        _stub("aligned", requires=("transcript",), hard=True, **overrides.get("aligned", {})),
        _stub("tagged", requires=("aligned",), **overrides.get("tagged", {})),
    )


def test_stages_run_in_declared_order(patch_stages, audio_file, tmp_path, monkeypatch):
    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    order: list[str] = []

    def tracking(name, **kw):
        base = _stub(name, **kw)

        def fn(ctx, _orig=base.fn, _name=name):
            order.append(_name)
            return _orig(ctx)

        return StageSpec(
            name=base.name, requires=base.requires, fn=fn, hard=base.hard,
            needs_hf=base.needs_hf, needs_ollama=base.needs_ollama,
        )

    patch_stages(
        (
            tracking("transcript", hard=True),
            tracking("aligned", requires=("transcript",), hard=True),
        )
    )

    run_batch(audio_file, BatchOptions())
    assert order == ["transcript", "aligned"]


def test_a_soft_stage_failure_leaves_earlier_work_intact(
    patch_stages, audio_file, tmp_path, monkeypatch
):
    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    patch_stages(_three_stage_chain(tagged={"fails": True}))

    paths = run_batch(audio_file, BatchOptions())
    manifest = read_json(paths.manifest_path)

    assert manifest["status"] == "partial"
    assert paths.has("transcript")
    assert paths.has("aligned")
    assert not paths.has("tagged")


def test_a_hard_stage_failure_aborts_the_run(patch_stages, audio_file, tmp_path, monkeypatch):
    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    patch_stages(_three_stage_chain(aligned={"fails": True}))

    paths = run_batch(audio_file, BatchOptions())
    manifest = read_json(paths.manifest_path)

    assert manifest["status"] == "failed"
    assert paths.has("transcript")
    assert not paths.has("aligned")
    # tagged must never even be attempted once a hard upstream stage aborts.
    assert manifest["stages"][-1]["name"] == "aligned"


def test_a_stage_with_unmet_requirements_is_skipped_not_attempted(
    patch_stages, audio_file, tmp_path, monkeypatch
):
    """diarization failing (soft) must cause a later stage requiring it to be
    skipped cleanly, rather than crashing on missing input."""
    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    patch_stages(
        (
            _stub("transcript", hard=False, fails=True),
            _stub("aligned", requires=("transcript",), hard=False),
        )
    )
    # transcript is soft here on purpose, to isolate the skip behaviour from
    # the hard-abort behaviour already covered above.

    paths = run_batch(audio_file, BatchOptions())
    manifest = read_json(paths.manifest_path)

    aligned_entry = next(s for s in manifest["stages"] if s["name"] == "aligned")
    assert aligned_entry["status"] == "skipped"
    assert "missing required input" in aligned_entry["error"]


def test_all_stages_succeeding_yields_completed_status(
    patch_stages, audio_file, tmp_path, monkeypatch
):
    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    patch_stages(_three_stage_chain())

    paths = run_batch(audio_file, BatchOptions())
    manifest = read_json(paths.manifest_path)
    assert manifest["status"] == "completed"


def test_resume_skips_stages_already_recorded_ok(patch_stages, audio_file, tmp_path, monkeypatch):
    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    ran: list[str] = []

    def tracking(name, **kw):
        base = _stub(name, **kw)

        def fn(ctx, _orig=base.fn, _n=name):
            ran.append(_n)
            return _orig(ctx)

        return StageSpec(
            name=base.name, requires=base.requires, fn=fn, hard=base.hard,
            needs_hf=base.needs_hf, needs_ollama=base.needs_ollama,
        )

    patch_stages(
        (
            tracking("transcript", hard=True),
            tracking("aligned", requires=("transcript",), hard=True, fails=True),
        )
    )
    first = run_batch(audio_file, BatchOptions())
    assert ran == ["transcript", "aligned"]
    assert read_json(first.manifest_path)["status"] == "failed"

    ran.clear()
    patch_stages(
        (
            tracking("transcript", hard=True),
            tracking("aligned", requires=("transcript",), hard=True),
        )
    )
    resumed = run_batch(None, BatchOptions(resume_run_id=first.run_id))

    # transcript already succeeded and its artifact still exists -- must not re-run.
    assert ran == ["aligned"]
    assert resumed.run_id == first.run_id
    assert read_json(resumed.manifest_path)["status"] == "completed"


def test_resume_recovers_the_original_audio_path_from_provenance(
    patch_stages, audio_file, tmp_path, monkeypatch
):
    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    patch_stages(_three_stage_chain(tagged={"fails": True}))

    first = run_batch(audio_file, BatchOptions())
    # Resume with audio_path=None -- must be recovered from the manifest.
    patch_stages(_three_stage_chain())
    resumed = run_batch(None, BatchOptions(resume_run_id=first.run_id))

    assert read_json(resumed.manifest_path)["status"] == "completed"


def test_force_deletes_the_stage_and_every_later_artifact(
    patch_stages, audio_file, tmp_path, monkeypatch
):
    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    patch_stages(_three_stage_chain())
    first = run_batch(audio_file, BatchOptions())
    assert first.has("tagged")

    reran: list[str] = []

    def tracking(name, **kw):
        base = _stub(name, **kw)

        def fn(ctx, _orig=base.fn, _n=name):
            reran.append(_n)
            return _orig(ctx)

        return StageSpec(
            name=base.name, requires=base.requires, fn=fn, hard=base.hard,
            needs_hf=base.needs_hf, needs_ollama=base.needs_ollama,
        )

    patch_stages(
        (
            tracking("transcript", hard=True),
            tracking("aligned", requires=("transcript",), hard=True),
            tracking("tagged", requires=("aligned",)),
        )
    )
    resumed = run_batch(None, BatchOptions(resume_run_id=first.run_id, force_stage="aligned"))

    # transcript (before the force point) must not be re-run; aligned and
    # everything after it must be.
    assert reran == ["aligned", "tagged"]
    assert read_json(resumed.manifest_path)["status"] == "completed"


def test_only_runs_a_single_named_stage(patch_stages, audio_file, tmp_path, monkeypatch):
    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    patch_stages(_three_stage_chain())
    first = run_batch(audio_file, BatchOptions())

    ran: list[str] = []

    def tracking(name, **kw):
        base = _stub(name, **kw)

        def fn(ctx, _orig=base.fn, _n=name):
            ran.append(_n)
            return _orig(ctx)

        return StageSpec(name=base.name, requires=base.requires, fn=fn, hard=base.hard)

    patch_stages(
        (
            tracking("transcript", hard=True),
            tracking("aligned", requires=("transcript",), hard=True),
        )
    )
    run_batch(
        None,
        BatchOptions(resume_run_id=first.run_id, only_stage="aligned", force_stage="aligned"),
    )
    assert ran == ["aligned"]


def test_skip_excludes_named_stages(patch_stages, audio_file, tmp_path, monkeypatch):
    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    patch_stages(_three_stage_chain())

    paths = run_batch(audio_file, BatchOptions(skip_stages=("tagged",)))
    manifest = read_json(paths.manifest_path)
    names = [s["name"] for s in manifest["stages"]]
    assert "tagged" not in names
    assert manifest["status"] == "completed"  # nothing selected failed


def test_unknown_stage_name_in_only_raises(patch_stages, audio_file, tmp_path, monkeypatch):
    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    patch_stages(_three_stage_chain())
    with pytest.raises(ValueError, match="Unknown stage"):
        run_batch(audio_file, BatchOptions(only_stage="not_a_real_stage"))


def test_missing_audio_file_raises_for_a_new_run(tmp_path, monkeypatch):
    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    with pytest.raises(ArtifactError, match="not found"):
        run_batch(tmp_path / "does-not-exist.wav", BatchOptions())


def test_resuming_a_nonexistent_run_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    with pytest.raises(ArtifactError, match="No such run"):
        run_batch(None, BatchOptions(resume_run_id="20200101-000000_batch_nope"))


def test_resume_under_a_changed_config_is_refused_before_touching_the_run(
    patch_stages, audio_file, tmp_path, monkeypatch
):
    from meeting_assistant.errors import ProvenanceError

    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    patch_stages(_three_stage_chain(tagged={"fails": True}))
    first = run_batch(audio_file, BatchOptions())
    before = first.manifest_path.read_bytes()

    monkeypatch.setattr(batch_mod.config, "OLLAMA_MODEL", "llama3.1:8b")
    patch_stages(_three_stage_chain())
    with pytest.raises(ProvenanceError):
        run_batch(None, BatchOptions(resume_run_id=first.run_id))

    assert first.manifest_path.read_bytes() == before
    assert not first.has("tagged")


def test_resume_attributes_the_stages_it_runs_to_a_new_execution(
    patch_stages, audio_file, tmp_path, monkeypatch
):
    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    patch_stages(_three_stage_chain(tagged={"fails": True}))
    first = run_batch(audio_file, BatchOptions())

    patch_stages(_three_stage_chain())
    run_batch(None, BatchOptions(resume_run_id=first.run_id))

    data = read_json(first.manifest_path)
    assert {s["name"]: s["execution"] for s in data["stages"]} == {
        "transcript": 0,
        "aligned": 0,
        "tagged": 1,
    }
    assert len(data["resumes"]) == 1


def test_a_resume_with_nothing_to_do_records_no_execution(
    patch_stages, audio_file, tmp_path, monkeypatch
):
    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    patch_stages(_three_stage_chain())
    first = run_batch(audio_file, BatchOptions())

    run_batch(None, BatchOptions(resume_run_id=first.run_id))

    assert read_json(first.manifest_path)["resumes"] == []


def test_the_api_create_then_execute_path_is_a_single_execution(
    patch_stages, audio_file, tmp_path, monkeypatch
):
    """create_batch_run followed by a resume must not look like a resumed run."""
    monkeypatch.setattr(batch_mod.config, "RUNS_DIR", tmp_path / "runs")
    patch_stages(_three_stage_chain())
    paths = batch_mod.create_batch_run(audio_file)

    run_batch(None, BatchOptions(resume_run_id=paths.run_id))

    data = read_json(paths.manifest_path)
    assert data["resumes"] == []
    assert data["consistency"] == {"executions": [0], "config": True, "code": True}
