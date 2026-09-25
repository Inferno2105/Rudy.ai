"""Tests for WER/CER, against small hand-computable cases.

No audio, no model -- every case here is a pair of strings whose expected
error counts can be checked by hand, which is what a metric implementation
used in a paper needs: the numbers must be independently verifiable, not just
"whatever the library returns."
"""

from __future__ import annotations

import pytest

from meeting_assistant.evaluation.asr_metrics import (
    character_error_rate,
    romanized_word_error_rate,
    word_error_rate,
)


def test_identical_text_has_zero_wer():
    result = word_error_rate("good morning everyone", "good morning everyone")
    assert result.wer == 0.0
    assert result.hits == 3
    assert result.substitutions == 0


def test_one_substitution_out_of_three_words():
    result = word_error_rate("good morning everyone", "good evening everyone")
    assert result.wer == pytest.approx(1 / 3)
    assert result.substitutions == 1
    assert result.hits == 2


def test_one_insertion_is_scored_against_reference_length():
    result = word_error_rate("good morning", "good morning everyone")
    assert result.wer == pytest.approx(0.5)  # 1 insertion / 2 reference words
    assert result.insertions == 1


def test_one_deletion_is_scored_against_reference_length():
    result = word_error_rate("good morning everyone", "good everyone")
    assert result.wer == pytest.approx(1 / 3)
    assert result.deletions == 1


def test_wer_ignores_case_and_punctuation():
    result = word_error_rate("Good Morning, Everyone!", "good morning everyone")
    assert result.wer == 0.0


def test_empty_reference_and_empty_hypothesis_is_perfect_agreement():
    result = word_error_rate("", "")
    assert result.wer == 0.0
    assert result.reference_words == 0


def test_empty_reference_with_nonempty_hypothesis_is_maximal_error():
    result = word_error_rate("", "unexpected words appeared")
    assert result.wer == 1.0
    assert result.insertions == 3


def test_as_dict_rounds_wer_to_four_places():
    result = word_error_rate("a b c", "a b d")
    d = result.as_dict()
    assert d["wer"] == round(d["wer"], 4)


# ---------------------------------------------------------------------------
# character_error_rate
# ---------------------------------------------------------------------------
def test_identical_text_has_zero_cer():
    result = character_error_rate("hello", "hello")
    assert result.cer == 0.0


def test_one_character_substitution():
    # "helo" vs "hello": 1 deletion out of 5 reference chars (space-stripped).
    result = character_error_rate("hello", "helo")
    assert result.cer == pytest.approx(1 / 5)


def test_cer_empty_reference_and_hypothesis_is_perfect_agreement():
    assert character_error_rate("", "").cer == 0.0


# ---------------------------------------------------------------------------
# romanized_word_error_rate -- the Hinglish cross-script comparison
# ---------------------------------------------------------------------------
def test_devanagari_hypothesis_against_devanagari_reference_matches():
    result = romanized_word_error_rate("नमस्ते दुनिया", "नमस्ते दुनिया")
    assert result.wer == 0.0


def test_devanagari_hypothesis_against_romanized_reference_is_comparable():
    """The entire point of this function: without romanizing both sides, a
    correct Devanagari transcription looks like a 100% wrong Latin one."""
    raw_wer = word_error_rate("namaste duniya", "नमस्ते दुनिया")
    assert raw_wer.wer == 1.0  # no shared script -- looks totally wrong

    romanized = romanized_word_error_rate("namaste duniya", "नमस्ते दुनिया")
    assert romanized.wer == 0.0  # actually the same words


def test_code_mixed_text_only_transliterates_the_devanagari_portion():
    result = romanized_word_error_rate("मीटिंग aaj hai", "मीटिंग aaj hai")
    assert result.wer == 0.0


def test_pure_latin_text_is_unaffected_by_romanization():
    result = romanized_word_error_rate("good morning everyone", "good evening everyone")
    assert result.wer == pytest.approx(1 / 3)
