"""Tests for the shared WER/CER text normalization policy.

Every case here is either a documented policy example or a regression case
for a concrete real bug found during development: a first version of
``normalize_text`` used ``[^\\w\\s'-]`` to strip punctuation and silently
deleted Devanagari combining marks along with it, turning "meeting" written
in Devanagari into three disconnected consonants. See the module docstring
for the full story; ``test_devanagari_combining_marks_survive`` is what would
have caught it.
"""

from __future__ import annotations

from meeting_assistant.evaluation.text_norm import DEFAULT_FILLERS, normalize_text


def test_lowercases_latin_text():
    assert normalize_text("Hello World") == "hello world"


def test_devanagari_has_no_case_and_is_left_alone():
    assert normalize_text("नमस्ते") == "नमस्ते"


def test_devanagari_combining_marks_survive():
    """The regression case: matras must not be treated as strippable
    punctuation just because Python's regex \\w does not match them."""
    assert normalize_text("मीटिंग") == "मीटिंग"
    assert normalize_text("हिन्दी और अंग्रेज़ी") == "हिन्दी और अंग्रेज़ी"


def test_devanagari_digits_map_to_ascii():
    assert normalize_text("१२ बजे") == "12 बजे"


def test_ordinary_punctuation_is_stripped():
    assert normalize_text("Hello, world!") == "hello world"


def test_intra_word_apostrophe_survives():
    assert normalize_text("don't stop") == "don't stop"


def test_intra_word_hyphen_survives():
    assert normalize_text("kya-baat hai") == "kya-baat hai"


def test_leading_and_trailing_hyphens_are_stripped():
    assert normalize_text("-- test --") == "test"
    assert normalize_text("word-") == "word"
    assert normalize_text("-word") == "word"


def test_leading_and_trailing_quotes_are_stripped():
    assert normalize_text("'quoted' word") == "quoted word"


def test_repeated_whitespace_collapses():
    assert normalize_text("  multiple   spaces  ") == "multiple spaces"


def test_zero_width_characters_are_removed():
    assert normalize_text("hello​world") == "helloworld"


def test_empty_string_normalizes_to_empty_string():
    assert normalize_text("") == ""


def test_is_idempotent():
    text = "Hello, दुनिया! It's kya-baat, ११ बजे।"
    once = normalize_text(text)
    twice = normalize_text(once)
    assert once == twice


def test_strip_fillers_removes_default_filler_words():
    result = normalize_text("um so basically matlab we are done", strip_fillers=True)
    assert result == "so we are done"


def test_strip_fillers_off_by_default_leaves_fillers_in_place():
    result = normalize_text("um so basically matlab we are done")
    for filler in ("um", "basically", "matlab"):
        assert filler in result.split(" ")


def test_default_fillers_set_is_lowercase():
    assert all(word == word.lower() for word in DEFAULT_FILLERS)
