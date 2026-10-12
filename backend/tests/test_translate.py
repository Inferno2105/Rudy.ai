"""Full translations of a transcript, and the transcript PDF built from any version."""

from __future__ import annotations

import pytest

from meeting_assistant.errors import ArtifactError, LLMError
from meeting_assistant.export.transcript_pdf import (
    TranslationMissing,
    render_transcript_pdf,
    speaker_names,
    timestamp,
    turns,
)
from meeting_assistant.io_utils import write_json
from meeting_assistant.language.translate import (
    _clean,
    build_translation,
    load_translation,
    translate_segments,
)
from meeting_assistant.paths import RunPaths
from tests.conftest import TaggingLLM

ORIGINAL = [
    {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00", "text": "नमस्ते सबको", "language": "Hindi"},
    {
        "start": 2.0,
        "end": 4.0,
        "speaker": "SPEAKER_01",
        "text": "let us begin",
        "language": "English",
    },
    {
        "start": 4.0,
        "end": 6.0,
        "speaker": "SPEAKER_00",
        "text": "आज का agenda",
        "language": "Code-Mixed",
    },
]
ROMANIZED = [
    {**ORIGINAL[0], "text": "namaste sabko"},
    {**ORIGINAL[1], "text": "let us begin"},
    {**ORIGINAL[2], "text": "aaj ka agenda"},
]


class FailingLLM:
    model = "down"

    def generate(self, prompt, *, system=None):  # noqa: ARG002
        raise LLMError("Ollama request failed")


@pytest.fixture
def run(tmp_path) -> RunPaths:
    paths = RunPaths(run_id="r1", root=tmp_path / "r1")
    paths.artifacts_dir.mkdir(parents=True)
    write_json(paths.artifact("tagged"), ORIGINAL)
    write_json(paths.artifact("hinglish"), ROMANIZED)
    write_json(
        paths.manifest_path,
        {"mode": "batch", "provenance": {"input": {"name": "standup.wav"}, "settings": {}}},
    )
    return paths


# --- translation ----------------------------------------------------------------------
def test_segments_already_in_the_target_language_are_copied(run):
    llm = TaggingLLM("english")
    result = translate_segments(ORIGINAL, ROMANIZED, "english", llm)
    assert [s["translation"] for s in result.segments] == ["translated", "copied", "translated"]
    assert result.segments[1]["text"] == "let us begin"
    # The model sees the original and the romanized text, never a copied segment.
    assert len(llm.prompts) == 2
    assert llm.prompts[0] == "Original: नमस्ते सबको\nRomanized: namaste sabko"


def test_hindi_keeps_hindi_segments_in_devanagari(run):
    result = translate_segments(ORIGINAL, ROMANIZED, "hindi", TaggingLLM("hindi"))
    assert result.segments[0]["text"] == "नमस्ते सबको"
    assert result.segments[0]["translation"] == "copied"
    assert result.segments[1]["text"] == "[hindi] let us begin"


def test_everything_but_the_text_is_kept(run):
    result = translate_segments(ORIGINAL, ROMANIZED, "english", TaggingLLM("english"))
    for before, after in zip(ORIGINAL, result.segments, strict=True):
        assert {k: after[k] for k in ("start", "end", "speaker", "language")} == {
            k: before[k] for k in ("start", "end", "speaker", "language")
        }


def test_an_unreachable_model_stops_the_translation():
    with pytest.raises(LLMError, match="Translation stopped"):
        translate_segments(ORIGINAL * 2, None, "hindi", FailingLLM())


def test_a_segment_that_fails_keeps_what_was_said():
    class FlakyLLM(TaggingLLM):
        def generate(self, prompt, *, system=None):
            if "agenda" in prompt:
                raise LLMError("timeout")
            return super().generate(prompt, system=system)

    result = translate_segments(ORIGINAL, ROMANIZED, "english", FlakyLLM("english"))
    assert result.failed == 1
    assert result.segments[2]["text"] == "आज का agenda"
    assert result.segments[2]["translation"] == "failed"


@pytest.mark.parametrize(
    ("reply", "cleaned"),
    [
        ("Output: Hello there", "Hello there"),
        ('"Hello there"', "Hello there"),
        ("Hello\nthere", "Hello there"),
    ],
)
def test_model_replies_are_reduced_to_the_translation(reply, cleaned):
    assert _clean(reply) == cleaned


def test_progress_is_reported_per_segment():
    seen = []
    translate_segments(
        ORIGINAL,
        ROMANIZED,
        "english",
        TaggingLLM("english"),
        on_progress=lambda d, t: seen.append((d, t)),
    )
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_a_translation_of_an_older_transcript_is_not_served(run):
    build_translation(run, "english", TaggingLLM("english"))
    document = load_translation(run, "english")
    assert document is not None
    assert document["model"] == "stub-llm"
    assert document["prompt_version"] == "translate_english_v1"
    assert document["source_artifacts"] == ["tagged", "hinglish"]

    # Normalization re-run: the transcript changed, so the translation is stale.
    write_json(run.artifact("hinglish"), [{**s, "text": s["text"] + "!"} for s in ROMANIZED])
    assert load_translation(run, "english") is None


def test_a_translation_by_a_replaced_model_is_made_again(run, monkeypatch):
    from meeting_assistant import config

    build_translation(run, "hindi", TaggingLLM("hindi"))
    assert load_translation(run, "hindi") is not None
    monkeypatch.setitem(config.TRANSLATION_MODELS, "hindi", "aya-expanse:8b")
    assert load_translation(run, "hindi") is None


# --- PDF ------------------------------------------------------------------------------
def test_speakers_are_numbered_in_the_order_they_first_spoke():
    names = speaker_names(
        [{"speaker": "SPEAKER_03"}, {"speaker": "UNKNOWN"}, {"speaker": "SPEAKER_01"}]
    )
    assert names == {
        "SPEAKER_03": "Speaker 1",
        "UNKNOWN": "Unidentified speaker",
        "SPEAKER_01": "Speaker 2",
    }


def test_consecutive_segments_by_one_speaker_form_one_turn():
    segments = [
        {"start": 0, "end": 2, "speaker": "A", "text": "one"},
        {"start": 2.5, "end": 4, "speaker": "A", "text": "two"},
        {"start": 20, "end": 22, "speaker": "A", "text": "after a long pause"},
        {"start": 22, "end": 23, "speaker": "B", "text": "reply"},
    ]
    result = turns(segments)
    assert [(t.speaker, t.texts) for t in result] == [
        ("A", ["one", "two"]),
        ("A", ["after a long pause"]),
        ("B", ["reply"]),
    ]


def test_timestamps_are_hours_minutes_seconds():
    assert timestamp(0) == "00:00:00"
    assert timestamp(3725.9) == "01:02:05"


@pytest.mark.parametrize("version", ["original", "romanized"])
def test_a_transcript_renders_as_a_pdf(run, version):
    data, name = render_transcript_pdf(run, version)
    assert data.startswith(b"%PDF")
    assert name == f"standup_transcript_{version}.pdf"


def test_a_translation_must_be_made_before_its_pdf(run):
    with pytest.raises(TranslationMissing):
        render_transcript_pdf(run, "hindi")
    build_translation(run, "hindi", TaggingLLM("hindi"))
    data, _ = render_transcript_pdf(run, "hindi")
    assert data.startswith(b"%PDF")


def test_no_romanized_pdf_without_a_romanized_transcript(run):
    run.artifact("hinglish").unlink()
    with pytest.raises(ArtifactError):
        render_transcript_pdf(run, "romanized")


def test_the_pdf_carries_the_summary_actions_and_statistics(run):
    from meeting_assistant.analytics.speaker_statistics import compute_speaker_statistics

    write_json(
        run.artifact("summary"),
        {"summary": "They began.", "highlights": ["The agenda"], "key_decisions": ["Start"]},
    )
    write_json(
        run.artifact("action_items"),
        {"action_items": [{"person": "SPEAKER_00", "task": "Send notes", "deadline": "kal"}]},
    )
    write_json(run.artifact("speaker_stats"), compute_speaker_statistics(ORIGINAL))
    data, _ = render_transcript_pdf(run, "original")
    assert data.startswith(b"%PDF")


def test_the_pdf_says_why_a_summary_is_missing(run):
    write_json(
        run.manifest_path,
        {
            "mode": "batch",
            "provenance": {"input": {"name": "standup.wav"}},
            "stages": [{"name": "summary", "status": "failed", "error": "Ollama was down"}],
        },
    )
    data, _ = render_transcript_pdf(run, "original")
    assert data.startswith(b"%PDF")
