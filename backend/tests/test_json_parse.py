"""Tests for recovering JSON from language-model replies.

The cases below are the shapes a local instruction-tuned model actually returns
despite being told to emit bare JSON: fenced blocks, a preamble sentence, a
closing remark. The nested-brace cases matter specifically for this project,
because summaries and action items quote meeting text back, and meeting text can
contain anything the speakers said.
"""

from __future__ import annotations

import pytest

from meeting_assistant.errors import LLMError
from meeting_assistant.llm.json_parse import extract_json


def test_bare_json_object():
    assert extract_json('{"summary": "ok"}') == {"summary": "ok"}


def test_fenced_json_block():
    raw = '```json\n{"summary": "ok"}\n```'
    assert extract_json(raw) == {"summary": "ok"}


def test_fenced_block_without_language_tag():
    assert extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_preamble_before_json():
    raw = 'Here is the JSON you requested:\n{"a": 1}'
    assert extract_json(raw) == {"a": 1}


def test_trailing_prose_after_json():
    raw = '{"a": 1}\n\nLet me know if you need anything else.'
    assert extract_json(raw) == {"a": 1}


def test_preamble_and_trailing_prose_together():
    raw = 'Sure! Here you go:\n```json\n{"a": 1}\n```\nHope that helps.'
    assert extract_json(raw) == {"a": 1}


def test_nested_objects_are_fully_captured():
    raw = 'Result:\n{"action_items": [{"person": "A", "task": "t"}]}\nDone.'
    assert extract_json(raw) == {"action_items": [{"person": "A", "task": "t"}]}


def test_braces_inside_string_values_do_not_truncate_the_object():
    """A greedy brace match would stop at the first closing brace in the text."""
    raw = 'Here:\n{"summary": "they discussed the {placeholder} syntax"}\nthanks'
    assert extract_json(raw) == {"summary": "they discussed the {placeholder} syntax"}


def test_escaped_quotes_inside_strings_are_handled():
    raw = r'{"summary": "he said \"ship it\" and left"}'
    assert extract_json(raw) == {"summary": 'he said "ship it" and left'}


def test_expect_list_extracts_an_array():
    raw = 'Segments:\n[{"text": "a"}, {"text": "b"}]'
    assert extract_json(raw, expect=list) == [{"text": "a"}, {"text": "b"}]


def test_wrong_top_level_type_is_rejected():
    """A list where a dict was expected must not reach the caller as valid."""
    with pytest.raises(LLMError, match="Expected a JSON dict"):
        extract_json('[1, 2, 3]')


def test_empty_response_raises():
    with pytest.raises(LLMError, match="empty response"):
        extract_json("   ")


def test_response_with_no_json_raises_and_includes_the_raw_text():
    """The raw reply must appear in the message.

    A malformed response is diagnosed by reading what the model said, and the
    previous implementation lost it: its handler referenced a variable that was
    out of scope (`raw if "raw" in dir()`), so the useful detail was dropped
    exactly when it was needed.
    """
    with pytest.raises(LLMError) as excinfo:
        extract_json("I'm sorry, I cannot help with that request.")
    assert "cannot help with that" in str(excinfo.value)


def test_malformed_json_raises_and_includes_the_raw_text():
    with pytest.raises(LLMError) as excinfo:
        extract_json('{"a": 1,,}')
    assert '{"a": 1,,}' in str(excinfo.value)


def test_very_long_raw_response_is_truncated_in_the_message():
    """Error messages go into logs; an unbounded dump would swamp them."""
    with pytest.raises(LLMError) as excinfo:
        extract_json("no json here " * 500)
    assert len(str(excinfo.value)) < 1000
