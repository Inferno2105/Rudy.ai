"""Tests for the `eval` CLI command's disk-loading glue.

The metric computation itself is already covered by
``tests/test_report.py`` and the individual metric-family test modules;
what is specific to this command is turning files under
``data/eval/references/<clip_id>/`` and a run directory's artifacts into the
``ClipReference``/``ClipHypothesis`` pair ``generate_clip_report`` expects --
and doing nothing destructive or crashing outright when no dataset has been
collected yet, which is the actual state of this project's real
``data/eval/`` right now.
"""

from __future__ import annotations

from meeting_assistant import config
from meeting_assistant.cli.main import _load_clip_hypothesis, _load_clip_reference, cmd_eval
from meeting_assistant.io_utils import write_json
from meeting_assistant.io_utils import write_text as _write_text
from meeting_assistant.paths import new_run
from meeting_assistant.pipeline.manifest import RunManifest


def _write_reference_clip(clip_dir):
    clip_dir.mkdir(parents=True)
    _write_text(clip_dir / "transcript.txt", "good morning everyone")
    _write_text(clip_dir / "summary.txt", "the team said good morning")
    write_json(
        clip_dir / "action_items.json", [{"person": "Riya", "task": "say hi", "deadline": None}]
    )
    write_json(clip_dir / "languages.json", ["English"])
    write_json(clip_dir / "true_speakers.json", ["Riya"])
    write_json(clip_dir / "meta.json", {"true_speaker_count": 1})


def test_load_clip_reference_reads_every_optional_file(tmp_path):
    _write_reference_clip(tmp_path / "clip01")
    reference = _load_clip_reference(tmp_path / "clip01")

    assert reference.transcript_text == "good morning everyone"
    assert reference.summary == "the team said good morning"
    assert reference.action_items == [{"person": "Riya", "task": "say hi", "deadline": None}]
    assert reference.languages == ["English"]
    assert reference.true_speakers == ["Riya"]
    assert reference.true_speaker_count == 1


def test_load_clip_reference_tolerates_a_partially_labelled_clip(tmp_path):
    """Only a transcript reference exists -- everything else must come back
    None rather than raise, so a clip can be labelled incrementally."""
    clip_dir = tmp_path / "clip02"
    clip_dir.mkdir(parents=True)
    _write_text(clip_dir / "transcript.txt", "hello")

    reference = _load_clip_reference(clip_dir)

    assert reference.transcript_text == "hello"
    assert reference.summary is None
    assert reference.action_items is None
    assert reference.turns is None


def test_load_clip_reference_reads_rttm_turns(tmp_path):
    from meeting_assistant.evaluation.rttm import write_rttm

    clip_dir = tmp_path / "clip03"
    clip_dir.mkdir(parents=True)
    write_rttm(
        clip_dir / "turns.rttm",
        [{"start": 0.0, "end": 5.0, "speaker": "A"}],
        file_id="clip03",
    )

    reference = _load_clip_reference(clip_dir)
    assert reference.turns == [{"start": 0.0, "end": 5.0, "speaker": "A"}]


def _write_completed_run(runs_dir, source_name):
    paths = new_run("batch", source_name, runs_dir=runs_dir)
    manifest = RunManifest.start(paths, mode="batch", audio_path=f"data/audio/{source_name}")
    tagged_segment = {
        "start": 0.0,
        "end": 2.0,
        "speaker": "SPEAKER_00",
        "language": "English",
        "text": "good morning everyone",
    }
    write_json(paths.artifact("tagged"), [tagged_segment])
    summary_artifact = {"summary": "greeting", "highlights": [], "key_decisions": []}
    write_json(paths.artifact("summary"), summary_artifact)
    manifest.record_stage("transcript", "ok", seconds=1.5, counts={"realtime_factor": 0.4})
    manifest.set_status("completed")
    return paths


def test_load_clip_hypothesis_reads_transcript_text_and_system_metrics(tmp_path):
    run = _write_completed_run(tmp_path / "runs", "clip01.wav")
    hypothesis = _load_clip_hypothesis(run)

    assert hypothesis.transcript_text == "good morning everyone"
    assert hypothesis.languages == ["English"]
    assert hypothesis.summary == "greeting"
    assert hypothesis.system_metrics == {"realtime_factor": 0.4, "transcribe_seconds": 1.5}


def test_cmd_eval_reports_when_no_references_exist(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")

    exit_code = cmd_eval(argparse_namespace())

    assert exit_code == 1
    assert "No labelled clips found" in capsys.readouterr().out


def test_cmd_eval_scores_a_clip_matched_to_its_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")

    _write_reference_clip(tmp_path / "eval" / "references" / "clip01")
    _write_completed_run(tmp_path / "runs", "clip01.wav")

    exit_code = cmd_eval(argparse_namespace())
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Scored 1/1 clip" in out
    assert (tmp_path / "eval" / "reports" / "latest.json").exists()


def test_cmd_eval_skips_a_clip_with_no_matching_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")

    _write_reference_clip(tmp_path / "eval" / "references" / "clip_never_run")

    exit_code = cmd_eval(argparse_namespace())
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "no eligible run found" in out


def argparse_namespace():
    import argparse

    return argparse.Namespace()


def test_cmd_eval_passes_over_a_run_with_mixed_configurations(tmp_path, monkeypatch, capsys):
    """A resumed run whose stages came from two configurations must never be scored."""
    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")

    _write_reference_clip(tmp_path / "eval" / "references" / "clip01")
    run = _write_completed_run(tmp_path / "runs", "clip01.wav")
    manifest = RunManifest.load(run)
    manifest.resumes.append({"execution": 1, "config_hash": "different", "git": {}})
    manifest.current_execution = 1
    manifest.record_stage("summary", "ok")

    exit_code = cmd_eval(argparse_namespace())
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "different configurations" in out
    assert "no eligible run found" in out


def test_cmd_eval_passes_over_a_synthetic_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")

    _write_reference_clip(tmp_path / "eval" / "references" / "clip01")
    run = _write_completed_run(tmp_path / "runs", "clip01.wav")
    manifest = RunManifest.load(run)
    manifest.data_origin = "synthetic"
    manifest.save()

    exit_code = cmd_eval(argparse_namespace())

    assert exit_code == 1
    assert "not 'real_audio'" in capsys.readouterr().out
