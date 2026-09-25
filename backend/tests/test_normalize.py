"""Tests for Hinglish normalization, against a fake LLM transport.

No real Ollama server or model is used — see ``conftest.py``'s ``fake_llm``
fixture. What matters here is the contract: failures never corrupt a segment or
abort the run, only the ``text`` field changes, and everything is counted so a
caller can tell a quiet run from a broken one.
"""

from __future__ import annotations

from meeting_assistant.language.normalize import normalize_text, normalize_transcript


def test_normalize_text_returns_the_models_output(fake_llm):
    client, _ = fake_llm(["Good morning, aaj hum test kar rahe hain"])
    text, ok = normalize_text("गुड मॉर्निंग, आज हम टेस्ट कर रहे हैं", client)
    assert ok is True
    assert text == "Good morning, aaj hum test kar rahe hain"


def test_normalize_text_sends_the_original_text_as_the_user_message(fake_llm):
    client, transport = fake_llm(["converted"])
    normalize_text("original text", client)
    assert transport.prompts == ["original text"]


def test_normalize_text_falls_back_to_the_original_on_failure(fake_llm):
    """A bad LLM call must never corrupt a segment -- the original is kept."""
    client, transport = fake_llm([])
    transport.chat = lambda **kw: (_ for _ in ()).throw(ConnectionError("down"))

    text, ok = normalize_text("आज हम मीटिंग करेंगे", client)
    assert ok is False
    assert text == "आज हम मीटिंग करेंगे"


def test_normalize_text_falls_back_when_model_returns_empty_string(fake_llm):
    """An empty completion is not an error, but must not silently blank the segment."""
    client, _ = fake_llm([""])
    text, ok = normalize_text("original", client)
    assert ok is True
    assert text == "original"


def test_normalize_transcript_only_changes_text(fake_llm):
    segments = [
        {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00", "language": "Hindi", "text": "आज"},
    ]
    client, _ = fake_llm(["aaj"])
    result = normalize_transcript(segments, client)

    normalized = result.segments[0]
    assert normalized["text"] == "aaj"
    assert normalized["start"] == 0.0
    assert normalized["end"] == 2.0
    assert normalized["speaker"] == "SPEAKER_00"
    # The language tag from the earlier detection stage must survive untouched.
    assert normalized["language"] == "Hindi"


def test_normalize_transcript_preserves_segment_order_and_count(fake_llm):
    segments = [
        {"start": 0, "text": "one"},
        {"start": 1, "text": "two"},
        {"start": 2, "text": "three"},
    ]
    client, _ = fake_llm(["1", "2", "3"])
    result = normalize_transcript(segments, client)
    assert [s["text"] for s in result.segments] == ["1", "2", "3"]


def test_normalize_transcript_counts_failures_without_aborting(fake_llm):
    """One bad segment must not stop the rest of the transcript from being normalized."""
    segments = [{"start": 0, "text": "a"}, {"start": 1, "text": "b"}, {"start": 2, "text": "c"}]
    client, transport = fake_llm(["ok-a", "ok-c"])

    calls = {"n": 0}
    real_chat = transport.chat

    def flaky_chat(**kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ConnectionError("transient failure")
        return real_chat(**kwargs)

    transport.chat = flaky_chat

    result = normalize_transcript(segments, client)
    assert result.failed_segments == 1
    assert len(result.segments) == 3
    assert result.segments[1]["text"] == "b"  # original preserved on failure


def test_normalize_transcript_of_empty_list():
    from meeting_assistant.llm.client import OllamaClient

    result = normalize_transcript([], OllamaClient())
    assert result.segments == []
    assert result.failed_segments == 0


def test_normalize_transcript_records_prompt_version(fake_llm):
    segments = [{"start": 0, "text": "x"}]
    client, _ = fake_llm(["y"])
    result = normalize_transcript(segments, client)
    assert result.prompt_version == "normalize_v1"


def test_manifest_dict_has_the_reportable_fields(fake_llm):
    segments = [{"start": 0, "text": "x"}]
    client, _ = fake_llm(["y"])
    result = normalize_transcript(segments, client)
    manifest = result.as_manifest_dict()
    assert manifest["segments"] == 1
    assert manifest["failed_segments"] == 0
    assert manifest["prompt_version"] == "normalize_v1"
