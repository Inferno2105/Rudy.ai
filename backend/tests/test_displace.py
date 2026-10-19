"""Importing the DISPLACE 2023 dev set as reference clips (a tiny stand-in corpus)."""

from __future__ import annotations

import json

import pytest

from meeting_assistant.errors import ArtifactError
from meeting_assistant.evaluation import displace
from meeting_assistant.evaluation.dataset import check_clip
from meeting_assistant.evaluation.references import read_clip


def _segment(start, end, speaker, language, content):
    return {
        "startTime": start,
        "endTime": end,
        "speaker": f"20221117_1445_X001_{speaker}_HiEn",
        "language": language,
        "content": content,
    }


HINDI_ENGLISH = [
    _segment(0.0, 1.0, "S1", "hi", "मुझे तो"),
    _segment(1.0, 1.6, "S1", "en", "comedy [laugh]"),
    _segment(1.2, 1.8, "S2", "En", "horror"),  # overlaps S1, other case
    _segment(2.0, 2.5, "S2", "hi", "[sil]"),  # silence only: not a turn
    _segment(3.0, 30.0, "S3", "Hi", "अच्छा [unkwn] लगता है"),
    _segment(30.0, 30.2, "S3", "sp", "नई"),  # unusable label: under 1% of the speech
]


def _corpus(tmp_path, sessions):
    root = tmp_path / "DEVSet_DISPLACE_Corpus" / "DEVSet_DISPLACE_Corpus"
    (root / "jsons").mkdir(parents=True)
    (root / "wav").mkdir()
    for session_id, segments in sessions.items():
        (root / "jsons" / f"{session_id}.json").write_text(
            json.dumps({session_id: segments}, ensure_ascii=False), encoding="utf-8"
        )
        (root / "wav" / f"{session_id}.wav").write_bytes(b"RIFF fake wav")
    return tmp_path / "DEVSet_DISPLACE_Corpus"


def test_tags_are_removed_but_fillers_and_words_are_kept():
    assert displace.clean_content("अच्छा [unkwn] hmm <img> ok [laugh]") == "अच्छा hmm ok"
    # A stray bracket from a typo in the release is dropped, its words kept.
    assert displace.clean_content("[power than Nepal [laugh]") == "power than Nepal"


def test_a_silence_only_segment_is_not_speech():
    assert not displace.is_speech({"content": "[sil]"})
    assert displace.is_speech({"content": "[laugh]"})  # someone is audibly there
    assert displace.is_speech({"content": "हाँ [sil]"})


def test_speaker_ids_are_shortened_to_their_seat():
    assert displace.speaker_label("20221117_1445_B020_S3_BaEn") == "S3"
    assert displace.speaker_label("someone") == "someone"


def test_only_hindi_english_sessions_are_imported(tmp_path):
    kannada = [
        _segment(0, 5, "S1", "en", "hello"),
        _segment(5, 6, "S1", "hi", "हाँ"),
        _segment(6, 9, "S2", "ka", "ನಮಸ್ಕಾರ"),
    ]
    english_only = [_segment(0, 5, "S1", "en", "hello there")]
    corpus = _corpus(tmp_path, {"X001": HINDI_ENGLISH, "K001": kannada, "E001": english_only})

    results = displace.import_corpus(corpus, tmp_path / "refs", tmp_path / "audio")

    by_id = {r.session_id: r for r in results}
    assert by_id["X001"].kept and by_id["X001"].clip_id == "displace-x001"
    assert not by_id["K001"].kept and "another language" in by_id["K001"].reason
    assert not by_id["E001"].kept and by_id["E001"].reason == "not both Hindi and English"
    assert sorted(p.name for p in (tmp_path / "audio").iterdir()) == ["displace-x001.wav"]


def test_an_imported_clip_reads_back_like_a_hand_labelled_one(tmp_path):
    corpus = _corpus(tmp_path, {"X001": HINDI_ENGLISH})
    displace.import_corpus(corpus, tmp_path / "refs", tmp_path / "audio")

    labels = read_clip(tmp_path / "refs" / "displace-x001")

    assert labels.transcript.split("\n") == [
        "मुझे तो", "comedy", "horror", "अच्छा लगता है", "नई"
    ]
    assert [t["speaker"] for t in labels.turns] == ["S1", "S1", "S2", "S3", "S3"]
    assert [(s["start"], s["language"]) for s in labels.language_spans] == [
        (0.0, "Hindi"), (1.0, "English"), (1.2, "English"), (3.0, "Hindi")
    ]
    meta = labels.meta
    assert meta["dataset"] == displace.DATASET and meta["speakers"] == 3
    assert meta["excluded"] == {
        "after_recording_end": 0,  # the stand-in audio has no readable length
        "non_speech_segments": 1,
        "segments_without_language": 1,
    }
    assert "redistributed" in meta["license"]


def test_the_dataset_check_accepts_an_imported_clip(tmp_path, monkeypatch):
    from meeting_assistant import config

    monkeypatch.setattr(config, "EVAL_DIR", tmp_path / "eval")
    monkeypatch.setattr(config, "AUDIO_DIR", tmp_path / "audio")
    corpus = _corpus(tmp_path, {"X001": HINDI_ENGLISH})
    displace.import_corpus(corpus, tmp_path / "eval" / "references", tmp_path / "audio")

    check = check_clip(tmp_path / "eval" / "references" / "displace-x001")

    # The stand-in audio is not a real WAV; everything else must pass,
    # overlapping language labels and the missing consent fields included.
    assert [e for e in check.errors if "WAV" not in e] == []
    assert check.status["meta"] == "ok" and check.status["languages"] == "ok"
    # A corpus without summaries is still completely labelled for what it scores.
    assert check.status["summary"] == check.status["actions"] == "n/a"


def test_a_hand_labelled_clip_is_never_overwritten(tmp_path):
    corpus = _corpus(tmp_path, {"X001": HINDI_ENGLISH})
    folder = tmp_path / "refs" / "displace-x001"
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text('{"condition": "code-mixed"}', encoding="utf-8")

    with pytest.raises(ArtifactError, match="not imported from DISPLACE"):
        displace.import_corpus(corpus, tmp_path / "refs", tmp_path / "audio")


def test_reimporting_reuses_the_audio_already_in_place(tmp_path):
    corpus = _corpus(tmp_path, {"X001": HINDI_ENGLISH})
    displace.import_corpus(corpus, tmp_path / "refs", tmp_path / "audio")

    again = displace.import_corpus(corpus, tmp_path / "refs", tmp_path / "audio")

    assert again[0].kept and again[0].audio == "kept"


def test_labels_past_the_end_of_the_recording_are_cut_at_it(tmp_path):
    session = displace.Session(
        "X001",
        [
            {"start": 0.0, "end": 2.0, "speaker": "a_S1_x", "language": "hi", "content": "हाँ"},
            {"start": 9.0, "end": 12.0, "speaker": "a_S2_x", "language": "en", "content": "ok"},
            {"start": 11.0, "end": 13.0, "speaker": "a_S1_x", "language": "en", "content": "bye"},
        ],
        tmp_path / "X001.wav",
    )

    folder = displace.write_clip(session, tmp_path / "refs", duration=10.0)

    labels = read_clip(folder)
    assert [(t["start"], t["end"]) for t in labels.turns] == [(0.0, 2.0), (9.0, 10.0)]
    assert labels.meta["excluded"]["after_recording_end"] == 2


def test_tuning_sessions_are_marked_and_reported_apart(tmp_path):
    from meeting_assistant.cli.main import _clip_set

    corpus = _corpus(tmp_path, {"M030": HINDI_ENGLISH, "X001": HINDI_ENGLISH})
    displace.import_corpus(corpus, tmp_path / "refs", tmp_path / "audio")

    tune, test = tmp_path / "refs" / "displace-m030", tmp_path / "refs" / "displace-x001"
    assert read_clip(tune).meta["split"] == "tune" and read_clip(test).meta["split"] == "test"
    assert _clip_set(tune, "real_audio") == "displace2023-dev:tune"
    assert _clip_set(test, "real_audio") == "displace2023-dev"
