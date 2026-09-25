"""Tests for LLM-based summarization, against a fake LLM transport."""

from __future__ import annotations

from meeting_assistant.intel.summarization import summarize_transcript


def _segments():
    return [
        {"start": 0, "speaker": "A", "text": "Let's discuss the backend status."},
        {"start": 5, "speaker": "B", "text": "It's almost done, API endpoints work."},
    ]


def test_successful_summary_populates_all_three_fields(fake_llm):
    client, _ = fake_llm(
        [
            '{"summary": "They discussed backend status.", '
            '"highlights": ["backend nearly done"], '
            '"key_decisions": []}'
        ]
    )
    result = summarize_transcript(_segments(), client)

    assert result.ok is True
    assert result.summary == "They discussed backend status."
    assert result.highlights == ["backend nearly done"]
    assert result.key_decisions == []


def test_empty_key_decisions_is_a_valid_result_not_an_error(fake_llm):
    """No explicit decision was made -- an empty list is correct, not a failure."""
    client, _ = fake_llm(
        [
            '{"summary": "General discussion, nothing decided.", '
            '"highlights": [], "key_decisions": []}'
        ]
    )
    result = summarize_transcript(_segments(), client)
    assert result.ok is True
    assert result.key_decisions == []


def test_malformed_llm_response_is_a_soft_failure(fake_llm):
    """The pipeline must be able to keep transcription/diarization results
    even when the LLM stage fails -- so this must not raise."""
    client, _ = fake_llm(["this is not json and has no braces at all"])
    result = summarize_transcript(_segments(), client)

    assert result.ok is False
    assert result.error is not None
    assert result.summary == ""
    assert result.highlights == []


def test_transport_failure_is_a_soft_failure(fake_llm):
    client, transport = fake_llm([])
    transport.chat = lambda **kw: (_ for _ in ()).throw(ConnectionError("down"))

    result = summarize_transcript(_segments(), client)
    assert result.ok is False
    error = (result.error or "").lower()
    assert "down" in error or "connectionerror" in error


def test_empty_transcript_short_circuits_without_calling_the_model(fake_llm):
    """Nothing to summarize; the model must never be asked to fill a blank."""
    client, transport = fake_llm(["should never be used"])
    result = summarize_transcript([], client)

    assert result.ok is True
    assert result.summary == ""
    assert transport.prompts == []


def test_transcript_of_only_empty_text_segments_short_circuits(fake_llm):
    client, transport = fake_llm(["unused"])
    result = summarize_transcript([{"start": 0, "text": "   "}], client)
    assert result.ok is True
    assert transport.prompts == []


def test_as_dict_matches_the_artifact_contract(fake_llm):
    client, _ = fake_llm(['{"summary": "s", "highlights": ["h"], "key_decisions": ["d"]}'])
    result = summarize_transcript(_segments(), client)
    assert result.as_dict() == {"summary": "s", "highlights": ["h"], "key_decisions": ["d"]}


def test_prompt_version_is_recorded(fake_llm):
    client, _ = fake_llm(['{"summary": "s", "highlights": [], "key_decisions": []}'])
    result = summarize_transcript(_segments(), client)
    assert result.prompt_version == "summarize_v1"


def test_manifest_dict_reports_failure_without_the_full_payload(fake_llm):
    client, transport = fake_llm([])
    transport.chat = lambda **kw: (_ for _ in ()).throw(ConnectionError("down"))
    result = summarize_transcript(_segments(), client)
    manifest = result.as_manifest_dict()
    assert manifest["ok"] is False
    assert manifest["error"]
    assert "summary" not in manifest


def test_non_string_highlights_are_coerced_to_strings(fake_llm):
    """A model that returns a number in a list must not break the artifact's type contract."""
    client, _ = fake_llm(['{"summary": "s", "highlights": [1, 2], "key_decisions": []}'])
    result = summarize_transcript(_segments(), client)
    assert result.highlights == ["1", "2"]
