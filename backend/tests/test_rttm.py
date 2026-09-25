"""Tests for RTTM read/write and Audacity label-track conversion."""

from __future__ import annotations

import pytest

from meeting_assistant.evaluation.rttm import labels_to_rttm, read_rttm, write_rttm


def test_write_then_read_round_trips_segments(tmp_path):
    segments = [
        {"start": 0.0, "end": 5.5, "speaker": "A"},
        {"start": 5.5, "end": 10.25, "speaker": "B"},
    ]
    path = write_rttm(tmp_path / "ref.rttm", segments, file_id="clip01")
    reloaded = read_rttm(path)

    assert reloaded == segments


def test_written_lines_use_rttm_speaker_format(tmp_path):
    segments = [{"start": 1.0, "end": 3.0, "speaker": "SPEAKER_00"}]
    path = write_rttm(tmp_path / "ref.rttm", segments, file_id="clip01")
    line = path.read_text(encoding="utf-8").strip()

    assert line == "SPEAKER clip01 1 1.000 2.000 <NA> <NA> SPEAKER_00 <NA> <NA>"


def test_write_rttm_with_no_segments_produces_an_empty_file(tmp_path):
    path = write_rttm(tmp_path / "empty.rttm", [], file_id="clip01")
    assert path.read_text(encoding="utf-8") == ""
    assert read_rttm(path) == []


def test_read_rttm_skips_blank_lines_and_non_speaker_lines(tmp_path):
    path = tmp_path / "mixed.rttm"
    path.write_text(
        "\n".join(
            [
                "SPEAKER clip01 1 0.000 2.000 <NA> <NA> A <NA> <NA>",
                "",
                ";; a comment some tools emit",
                "NOISE clip01 1 2.000 0.500 <NA> <NA> <NA> <NA> <NA>",
                "SPEAKER clip01 1 2.500 1.500 <NA> <NA> B <NA> <NA>",
            ]
        ),
        encoding="utf-8",
    )
    segments = read_rttm(path)
    assert [s["speaker"] for s in segments] == ["A", "B"]


def test_labels_to_rttm_converts_audacity_export(tmp_path):
    label_path = tmp_path / "labels.txt"
    label_path.write_text("0.000000\t5.500000\tA\n5.500000\t10.250000\tB\n", encoding="utf-8")

    segments = labels_to_rttm(label_path)

    assert segments == [
        {"start": 0.0, "end": 5.5, "speaker": "A"},
        {"start": 5.5, "end": 10.25, "speaker": "B"},
    ]


def test_labels_to_rttm_skips_blank_lines(tmp_path):
    label_path = tmp_path / "labels.txt"
    label_path.write_text("0.0\t1.0\tA\n\n1.0\t2.0\tB\n", encoding="utf-8")
    segments = labels_to_rttm(label_path)
    assert len(segments) == 2


def test_labels_to_rttm_raises_on_a_malformed_line(tmp_path):
    label_path = tmp_path / "labels.txt"
    label_path.write_text("0.0\t1.0\n", encoding="utf-8")  # missing the label field
    with pytest.raises(ValueError, match="labels.txt"):
        labels_to_rttm(label_path)
