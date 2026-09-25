"""Tests for the Ollama client, against a fake transport.

No server is contacted. That is the payoff of injecting the client into the
stages that use it: the retry policy and the usage accounting are testable in
milliseconds, where previously they would have needed a running 7B model.
"""

from __future__ import annotations

import pytest

from meeting_assistant.errors import LLMError


def test_generate_returns_stripped_content(fake_llm):
    client, _ = fake_llm(["  hello world  "])
    assert client.generate("prompt") == "hello world"


def test_generate_sends_system_prompt_first(fake_llm):
    client, transport = fake_llm(["ok"])
    client.generate("the user text", system="the system rules")
    assert transport.prompts == ["the user text"]


def test_usage_accumulates_across_calls(fake_llm):
    """Latency and token counts are reported results, not debug output."""
    client, _ = fake_llm(["a", "b"])
    client.generate("one")
    client.generate("two")

    usage = client.usage.as_dict()
    assert usage["calls"] == 2
    assert usage["prompt_tokens"] == 22
    assert usage["completion_tokens"] == 14
    assert usage["total_seconds"] >= 0.0


def test_generate_json_parses_a_good_first_reply(fake_llm):
    client, transport = fake_llm(['{"summary": "fine"}'])
    assert client.generate_json("prompt") == {"summary": "fine"}
    assert len(transport.prompts) == 1
    assert client.usage.retries == 0


def test_generate_json_retries_once_then_succeeds(fake_llm):
    client, transport = fake_llm(["not json at all", '{"summary": "recovered"}'])
    assert client.generate_json("prompt") == {"summary": "recovered"}
    assert len(transport.prompts) == 2
    assert client.usage.retries == 1


def test_retry_restates_the_requirement_rather_than_resending(fake_llm):
    """Resending an identical prompt to a low-temperature model is pointless.

    It reproduces the same malformed reply, so the retry has to actually change
    the instruction for the second attempt to be worth its cost in CPU time.
    """
    client, transport = fake_llm(["prose", '{"ok": true}'])
    client.generate_json("summarize this")

    first, second = transport.prompts
    assert first == "summarize this"
    assert second != first
    assert "ONLY the raw JSON" in second


def test_generate_json_raises_after_exhausting_retries(fake_llm):
    client, _ = fake_llm(["nope", "still nope"])
    with pytest.raises(LLMError):
        client.generate_json("prompt")
    assert client.usage.failures == 1


def test_generate_json_can_be_told_not_to_retry(fake_llm):
    client, transport = fake_llm(["nope", '{"ok": true}'])
    with pytest.raises(LLMError):
        client.generate_json("prompt", retries=0)
    assert len(transport.prompts) == 1


def test_transport_failure_is_wrapped_with_remediation(fake_llm):
    """A connection error must tell the user what to start, not just fail."""
    client, transport = fake_llm([])

    def boom(**kwargs):
        raise ConnectionError("connection refused")

    transport.chat = boom

    with pytest.raises(LLMError) as excinfo:
        client.generate("prompt")
    message = str(excinfo.value)
    assert "ollama pull" in message
    assert client.usage.failures == 1


def test_expect_list_is_forwarded_to_the_parser(fake_llm):
    client, _ = fake_llm(['[{"a": 1}]'])
    assert client.generate_json("prompt", expect=list) == [{"a": 1}]


def test_temperature_is_low_by_default():
    """Every model use here is extraction or conversion; invention is the failure."""
    from meeting_assistant.llm.client import OllamaClient

    assert OllamaClient().temperature <= 0.2
