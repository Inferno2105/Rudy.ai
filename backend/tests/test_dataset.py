"""The evaluation dataset's label folders: templates, the check, the blind copy."""

from __future__ import annotations

import argparse
import json

import numpy as np
import pytest

from meeting_assistant import config
from meeting_assistant.audio.wav_io import save_wav
from meeting_assistant.cli.main import cmd_dataset
from meeting_assistant.evaluation import dataset
from meeting_assistant.evaluation.references import LabelError, read_action_items, read_clip

TAB = "\t"


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(config, "AUDIO_DIR", tmp_path / "audio")
    (tmp_path / "audio").mkdir()
    return tmp_path


def _recording(data, clip_id="clip01", seconds=10):
    return save_wav(
        data / "audio" / f"{clip_id}.wav", np.zeros(16000 * seconds, dtype=np.int16), 16000
    )


def _track(*spans):
    return "".join(f"{start:.6f}{TAB}{end:.6f}{TAB}{label}\n" for start, end, label in spans)


def _label_completely(folder):
    (folder / "transcript.txt").write_text(
        "आज हम meeting शुरू करते हैं and then we review the plan together\n", encoding="utf-8"
    )
    (folder / "turns.txt").write_text(_track((0, 5, "P01"), (5, 9.5, "P02")), encoding="utf-8")
    (folder / "languages.txt").write_text(_track((0, 5, "M"), (5, 9.5, "E")), encoding="utf-8")
    (folder / "summary.txt").write_text(
        "The team opened the meeting and reviewed the release plan. They agreed that testing "
        "finishes tomorrow and the release goes out on Friday.",
        encoding="utf-8",
    )
    (folder / "action_items.txt").write_text("P02 | finish testing | tomorrow\n", encoding="utf-8")
    (folder / "rubric.txt").write_text(
        "faithfulness: 3\ncoverage: 2\nno_invention: 3\n", encoding="utf-8"
    )
    (folder / "meta.json").write_text(
        json.dumps(
            {
                "condition": "code-mixed",
                "speakers": 2,
                "device": "laptop microphone",
                "recorded_on": "2026-10-14",
                "participants": ["P01", "P02"],
                "notes": "",
            }
        ),
        encoding="utf-8",
    )


# --- dataset new ------------------------------------------------------------------
def test_new_clip_creates_templates_that_count_as_not_done(data):
    _recording(data)
    folder, notes = dataset.new_clip("clip01")
    assert notes == []
    assert {p.name for p in folder.iterdir()} == {
        "transcript.txt",
        "summary.txt",
        "action_items.txt",
        "rubric.txt",
        "meta.json",
    }
    check = dataset.check_clip(folder)
    assert check.errors == []
    assert check.status["audio"] == dataset.OK
    assert all(check.status[item] == dataset.MISSING for item in dataset.ITEMS[1:])


def test_new_clip_notes_a_missing_recording(data):
    _, notes = dataset.new_clip("clip02")
    assert "No recording yet" in notes[0]


@pytest.mark.parametrize("bad", ["Clip 1", "../escape", "", "UPPER"])
def test_new_clip_refuses_bad_ids(data, bad):
    with pytest.raises(ValueError):
        dataset.new_clip(bad)


def test_new_clip_never_overwrites(data):
    dataset.new_clip("clip01")
    with pytest.raises(ValueError, match="already exists"):
        dataset.new_clip("clip01")


# --- dataset check ------------------------------------------------------------------
def test_a_completely_labelled_clip_passes(data):
    _recording(data)
    folder, _ = dataset.new_clip("clip01")
    _label_completely(folder)
    check = dataset.check_clip(folder)
    assert check.errors == [], check.errors
    assert check.complete


def test_the_check_names_each_mistake(data):
    _recording(data, seconds=10)
    folder, _ = dataset.new_clip("clip01")
    _label_completely(folder)
    (folder / "languages.txt").write_text(
        _track((0, 6, "Hindi"), (5, 9, "English")), encoding="utf-8"
    )
    (folder / "turns.txt").write_text(_track((0, 30, "P01")), encoding="utf-8")
    (folder / "transcript.txt").write_text("we meet at 5 pm\n", encoding="utf-8")
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    meta.update(condition="noisy", participants=["Riya"])
    (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    check = dataset.check_clip(folder)
    text = "\n".join(check.errors + check.warnings)
    assert "two labels overlap at 0:05" in text
    assert "after the recording ends" in text
    assert "condition must be one of" in text
    assert "speakers says 2, but turns.txt names 1" in text
    assert "digits" in text
    assert "consent-form ids" in text
    assert not check.complete


def test_an_unknown_language_label_says_what_to_use(data):
    _recording(data)
    folder, _ = dataset.new_clip("clip01")
    (folder / "languages.txt").write_text(_track((0, 2, "Hinglish")), encoding="utf-8")
    check = dataset.check_clip(folder)
    assert check.status["languages"] == dataset.PROBLEM
    assert "use Hindi, English or Code-Mixed (or H, E, M)" in check.errors[0]


def test_a_point_label_is_reported(data):
    _recording(data)
    folder, _ = dataset.new_clip("clip01")
    (folder / "turns.txt").write_text(_track((3, 3, "P01")), encoding="utf-8")
    check = dataset.check_clip(folder)
    assert "drag the label across a region" in check.errors[0]


def test_a_missing_recording_is_reported(data):
    folder, _ = dataset.new_clip("clip01")
    check = dataset.check_clip(folder)
    assert check.status["audio"] == dataset.PROBLEM
    assert "recording not found" in check.errors[0]


def test_action_items_none_means_no_items_and_empty_means_not_done(data):
    folder, _ = dataset.new_clip("clip01")
    assert read_action_items(folder) is None
    (folder / "action_items.txt").write_text("# note\nnone\n", encoding="utf-8")
    assert read_action_items(folder) == []
    (folder / "action_items.txt").write_text("Riya, send notes\n", encoding="utf-8")
    with pytest.raises(LabelError, match="person \\| task \\| deadline"):
        read_action_items(folder)


# --- blind copy and agreement ---------------------------------------------------------
def test_blind_copy_keeps_times_and_hides_labels(data):
    _recording(data)
    folder, _ = dataset.new_clip("clip01")
    _label_completely(folder)
    target, count = dataset.blind_copy("clip01")
    assert count == 2
    assert "M" not in target.read_text(encoding="utf-8")
    assert target.read_text(encoding="utf-8").count("?") == 2

    # Until every '?' is replaced, the check says so.
    check = dataset.check_clip(folder)
    assert check.second_annotator == dataset.PROBLEM
    assert "not labelled yet" in check.errors[0]

    target.write_text(_track((0, 5, "Code-Mixed"), (5, 9.5, "Hindi")), encoding="utf-8")
    assert dataset.check_clip(folder).second_annotator == dataset.OK
    labels = read_clip(folder)
    assert [s["language"] for s in labels.second_language_spans] == ["Code-Mixed", "Hindi"]


def test_blind_copy_refuses_to_overwrite(data):
    _recording(data)
    folder, _ = dataset.new_clip("clip01")
    _label_completely(folder)
    dataset.blind_copy("clip01")
    with pytest.raises(ValueError, match="already exists"):
        dataset.blind_copy("clip01")


def test_second_annotator_must_not_move_the_stretches(data):
    _recording(data)
    folder, _ = dataset.new_clip("clip01")
    _label_completely(folder)
    (folder / "languages_b.txt").write_text(_track((0, 4, "M"), (4, 9.5, "E")), encoding="utf-8")
    check = dataset.check_clip(folder)
    assert check.second_annotator == dataset.PROBLEM
    assert "only change the labels, never the times" in "\n".join(check.errors)


# --- the command ------------------------------------------------------------------------
def test_check_command_prints_a_table_and_fails_on_problems(data, capsys):
    _recording(data)
    dataset.new_clip("clip01")
    dataset.new_clip("clip02")  # no recording
    code = cmd_dataset(argparse.Namespace(dataset_cmd="check", clip_id=None))
    out = capsys.readouterr().out
    assert code == 1
    assert out.splitlines()[0].split()[:3] == ["clip", "length", "audio"]
    assert "0 of 2 clip(s) completely labelled; 1 with something to fix." in out


def test_check_command_reports_agreement(data, capsys):
    _recording(data)
    folder, _ = dataset.new_clip("clip01")
    _label_completely(folder)
    (folder / "languages_b.txt").write_text(_track((0, 5, "M"), (5, 9.5, "H")), encoding="utf-8")
    code = cmd_dataset(argparse.Namespace(dataset_cmd="check", clip_id="clip01"))
    out = capsys.readouterr().out
    assert code == 0
    assert "Annotator agreement so far" in out and "50% identical labels" in out


def test_the_rubric_reads_scores_and_rejects_out_of_range_ones(tmp_path):
    import pytest

    from meeting_assistant.evaluation.references import LabelError, read_rubric

    path = tmp_path / "rubric.txt"
    def write(*lines):
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    write("# note", "faithfulness: 3", "coverage:", "no_invention: 2")
    assert read_rubric(tmp_path) is None  # coverage not scored yet
    write("faithfulness: 3", "coverage: 1", "no invention: 2")
    assert read_rubric(tmp_path) == {"faithfulness": 3, "coverage": 1, "no_invention": 2}
    write("faithfulness: 5")
    with pytest.raises(LabelError, match="must be 1-3"):
        read_rubric(tmp_path)
    write("clarity: 2")
    with pytest.raises(LabelError, match="not a criterion"):
        read_rubric(tmp_path)
