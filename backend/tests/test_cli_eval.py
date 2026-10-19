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
    _write_text(clip_dir / "transcript.txt", "# template note, ignored\ngood morning everyone")
    _write_text(clip_dir / "summary.txt", "the team said good morning")
    _write_text(clip_dir / "action_items.txt", "Riya | say hi | -\n")
    _write_text(clip_dir / "turns.txt", "0.000000\t2.000000\tRiya\n")
    _write_text(clip_dir / "languages.txt", "0.000000\t2.000000\tE\n")
    write_json(clip_dir / "meta.json", {"speakers": 1})


def test_load_clip_reference_reads_every_optional_file(tmp_path):
    _write_reference_clip(tmp_path / "clip01")
    reference = _load_clip_reference(tmp_path / "clip01")

    assert reference.transcript_text == "good morning everyone"
    assert reference.summary == "the team said good morning"
    assert reference.action_items == [{"person": "Riya", "task": "say hi", "deadline": None}]
    assert reference.turns == [{"start": 0.0, "end": 2.0, "speaker": "Riya"}]
    assert reference.language_spans == [{"start": 0.0, "end": 2.0, "language": "English"}]
    assert reference.true_speaker_count == 1


def test_load_clip_reference_still_reads_the_older_json_formats(tmp_path):
    clip_dir = tmp_path / "clip09"
    clip_dir.mkdir()
    write_json(
        clip_dir / "action_items.json", [{"person": "Riya", "task": "say hi", "deadline": None}]
    )
    write_json(clip_dir / "meta.json", {"true_speaker_count": 2})
    reference = _load_clip_reference(clip_dir)
    assert reference.action_items == [{"person": "Riya", "task": "say hi", "deadline": None}]
    assert reference.true_speaker_count == 2


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
    raw_segment = {"start": 0.0, "end": 2.0, "text": "good morning everyone"}
    write_json(paths.artifact("transcript"), [raw_segment])
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
    assert [s["language"] for s in hypothesis.resolved_segments] == ["English"]
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


def test_cmd_eval_scores_synthetic_runs_apart_from_real_recordings(tmp_path, monkeypatch, capsys):
    """Generated speech is scored, but never mixed into the real-recording numbers."""
    from meeting_assistant.io_utils import read_json

    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    for clip_id in ("clip01", "clip02"):
        _write_reference_clip(tmp_path / "eval" / "references" / clip_id)
    _write_completed_run(tmp_path / "runs", "clip01.wav")
    synthetic = RunManifest.load(_write_completed_run(tmp_path / "runs", "clip02.wav"))
    synthetic.data_origin = "synthetic"
    synthetic.save()

    assert cmd_eval(argparse_namespace()) == 0
    out = capsys.readouterr().out
    report = read_json(tmp_path / "eval" / "reports" / "latest.json")

    origins = {clip["clip_id"]: clip["source"]["data_origin"] for clip in report["clips"]}
    assert origins == {"clip01": "real_audio", "clip02": "synthetic"}
    assert report["aggregate"]["num_clips"] == 1
    assert report["aggregate_synthetic"]["num_clips"] == 1
    assert "clip02: scored against run" in out and "(synthetic)" in out
    assert "1 recorded, 1 synthetic" in out


def test_cmd_eval_reports_no_synthetic_aggregate_when_every_clip_is_real(tmp_path, monkeypatch):
    from meeting_assistant.io_utils import read_json

    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    _write_reference_clip(tmp_path / "eval" / "references" / "clip01")
    _write_completed_run(tmp_path / "runs", "clip01.wav")

    assert cmd_eval(argparse_namespace()) == 0
    report = read_json(tmp_path / "eval" / "reports" / "latest.json")
    assert report["aggregate_synthetic"] is None
    assert report["aggregate"]["num_clips"] == 1


def test_cmd_eval_records_which_run_each_clip_was_scored_against(tmp_path, monkeypatch):
    """Without this a report holds numbers with no trace back to their run."""
    from meeting_assistant.io_utils import read_json

    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    _write_reference_clip(tmp_path / "eval" / "references" / "clip01")
    run = _write_completed_run(tmp_path / "runs", "clip01.wav")

    assert cmd_eval(argparse_namespace()) == 0
    report = read_json(tmp_path / "eval" / "reports" / "latest.json")

    manifest = RunManifest.load(run)
    source = report["clips"][0]["source"]
    assert source["run_id"] == run.run_id
    assert source["config_hash"] == manifest.provenance_block["config_hash"]
    assert report["config_hashes"] == [source["config_hash"]]
    assert "generated_at" in report and "git" in report
    # Provenance is not a metric family and must not be "averaged".
    assert "source" not in report["aggregate"]


def test_cmd_eval_scores_language_by_time_and_records_agreement(tmp_path, monkeypatch):
    from meeting_assistant.io_utils import read_json

    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    clip_dir = tmp_path / "eval" / "references" / "clip01"
    _write_reference_clip(clip_dir)
    _write_text(clip_dir / "languages_b.txt", "0.000000\t2.000000\tEnglish\n")
    _write_completed_run(tmp_path / "runs", "clip01.wav")

    assert cmd_eval(argparse_namespace()) == 0
    report = read_json(tmp_path / "eval" / "reports" / "latest.json")

    language = report["clips"][0]["language_id"]
    assert language["accuracy"] == 1.0
    assert language["segments_scored"] == 1
    agreement = report["annotator_agreement"]
    assert agreement["stretches"] == 1 and agreement["observed_agreement"] == 1.0
    assert agreement["cohens_kappa"] is None  # one label only: kappa is undefined


def test_cmd_eval_skips_a_clip_whose_labels_cannot_be_read(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    clip_dir = tmp_path / "eval" / "references" / "clip01"
    _write_reference_clip(clip_dir)
    _write_text(clip_dir / "languages.txt", "0.0\t2.0\tHinglish\n")
    _write_completed_run(tmp_path / "runs", "clip01.wav")

    assert cmd_eval(argparse_namespace()) == 1
    out = capsys.readouterr().out
    assert "[skip] clip01" in out and "dataset check" in out


def test_asr_is_scored_on_whispers_output_not_the_romanized_rewrite(tmp_path):
    """WER_raw measures recognition alone: the normalize stage's Latin-script
    rewrite must never stand in for what Whisper heard."""
    run = _write_completed_run(tmp_path / "runs", "clip01.wav")
    write_json(run.artifact("transcript"), [{"start": 0.0, "end": 2.0, "text": "सुप्रभात सब"}])
    write_json(
        run.artifact("hinglish"),
        [{"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00", "language": "Hindi",
          "text": "suprabhat sab"}],
    )

    hypothesis = _load_clip_hypothesis(run)

    assert hypothesis.transcript_text == "सुप्रभात सब"
    assert hypothesis.resolved_segments[0]["text"] == "suprabhat sab"  # language, speakers


def test_cmd_eval_reports_a_published_corpus_as_its_own_set(tmp_path, monkeypatch, capsys):
    from meeting_assistant.io_utils import read_json

    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    _write_reference_clip(tmp_path / "eval" / "references" / "clip01")
    external = tmp_path / "eval" / "references" / "displace-x001"
    _write_reference_clip(external)
    write_json(external / "meta.json", {"dataset": "displace2023-dev", "speakers": 1})
    _write_completed_run(tmp_path / "runs", "clip01.wav")
    _write_completed_run(tmp_path / "runs", "displace-x001.wav")

    assert cmd_eval(argparse_namespace()) == 0
    report = read_json(tmp_path / "eval" / "reports" / "latest.json")

    sets = {clip["clip_id"]: clip["source"]["dataset"] for clip in report["clips"]}
    assert sets == {"clip01": "recorded", "displace-x001": "displace2023-dev"}
    assert report["aggregate"]["num_clips"] == 1
    assert report["aggregate_external"]["displace2023-dev"]["num_clips"] == 1
    assert "1 recorded, 0 synthetic, 1 displace2023-dev" in capsys.readouterr().out


def test_cmd_eval_takes_the_run_that_started_last_not_the_last_folder_name(tmp_path, monkeypatch):
    """A container stamps run ids in UTC and the host in local time, so a
    newer GPU run can sort before an older native run by folder name."""
    import meeting_assistant.paths as paths_mod
    from meeting_assistant.io_utils import read_json

    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    _write_reference_clip(tmp_path / "eval" / "references" / "clip01")
    runs = {}
    for run_id, started in (
        ("20261019-134216_batch_clip01", "2026-10-19T13:42:16+05:30"),  # native, older
        ("20261019-085810_batch_clip01", "2026-10-19T08:58:10+00:00"),  # container, newer
    ):
        monkeypatch.setattr(paths_mod, "make_run_id", lambda *a, run_id=run_id, **k: run_id)
        run = _write_completed_run(tmp_path / "runs", "clip01.wav")
        manifest = RunManifest.load(run)
        manifest.provenance_block["captured_at"] = started
        manifest.save()
        runs[run_id] = run

    assert cmd_eval(argparse_namespace()) == 0
    report = read_json(tmp_path / "eval" / "reports" / "latest.json")
    assert report["clips"][0]["source"]["run_id"] == "20261019-085810_batch_clip01"


def test_run_timestamps_carry_their_utc_offset():
    from datetime import datetime

    from meeting_assistant import provenance

    stamp = provenance.capture()["captured_at"]
    assert datetime.fromisoformat(stamp).tzinfo is not None


def test_cmd_eval_breaks_each_set_down_by_condition_and_reports_live_capture(tmp_path, monkeypatch):
    from meeting_assistant.io_utils import read_json

    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    for clip_id, condition in (("clip01", "hindi-dominant"), ("clip02", "adverse")):
        clip_dir = tmp_path / "eval" / "references" / clip_id
        _write_reference_clip(clip_dir)
        write_json(clip_dir / "meta.json", {"speakers": 1, "condition": condition})
        run = _write_completed_run(tmp_path / "runs", f"{clip_id}.wav")
    manifest = RunManifest.load(run)
    manifest.set_extra("live_stats", {"chunks_recorded": 7, "chunks_processed": 7,
                                      "mean_chunk_latency_sec": 2.5})

    assert cmd_eval(argparse_namespace()) == 0
    report = read_json(tmp_path / "eval" / "reports" / "latest.json")

    by_condition = report["aggregate_by_condition"]["recorded"]
    assert sorted(by_condition) == ["adverse", "hindi-dominant"]
    assert by_condition["adverse"]["num_clips"] == 1
    live = next(c for c in report["clips"] if c["clip_id"] == "clip02")["system"]
    assert live["live_chunks_recorded"] == live["live_chunks_processed"] == 7
