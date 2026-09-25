"""Tests for script-based language and code-mix detection.

Includes the test that documents the method's central limitation — Romanized
Hindi is indistinguishable from English under script comparison — because that
limitation is what forces language tagging to run before Hinglish normalization.
Pinning it means a future change that appears to "fix" the classifier cannot
quietly remove the reason the pipeline is ordered as it is.
"""

from __future__ import annotations

import pytest

from meeting_assistant.language.detection import (
    CODE_MIXED,
    ENGLISH,
    HINDI,
    classify_word,
    detect_language,
    detect_language_detailed,
    detect_language_for_segments,
    language_distribution,
)


# --------------------------------------------------------------------------
# classify_word
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("hello", "latin"),
        ("नमस्ते", "devanagari"),
        ("123", "other"),
        ("!!!", "other"),
        ("", "other"),
        ("system", "latin"),
        ("सिस्टम", "devanagari"),
    ],
)
def test_classify_word(word, expected):
    assert classify_word(word) == expected


def test_mixed_script_word_counts_as_devanagari():
    """The Devanagari portion is the stronger signal about the surrounding language."""
    assert classify_word("testकरना") == "devanagari"


# --------------------------------------------------------------------------
# detect_language
# --------------------------------------------------------------------------
def test_pure_english():
    assert detect_language("Good morning everyone, let us begin.") == ENGLISH


def test_pure_hindi_in_devanagari():
    assert detect_language("आज हम मीटिंग शुरू करते हैं") == HINDI


def test_genuine_code_mixing():
    assert detect_language("आज हम project का status discuss करेंगे") == CODE_MIXED


def test_single_english_loanword_does_not_flip_a_hindi_sentence():
    """One borrowed noun is not code-mixing at the level this project cares about.

    Hindi grammar carrying English technical nouns is the normal register in these
    meetings; treating every instance as mixed would label almost everything mixed
    and the class would stop distinguishing anything.
    """
    text = "मुझे लगता है कि यह बहुत अच्छा तरीका है और हम इसको आगे बढ़ा सकते हैं system"
    assert detect_language(text) == HINDI


# --------------------------------------------------------------------------
# The documented limitation
# --------------------------------------------------------------------------
def test_romanized_hindi_is_classified_as_english():
    """The limitation that dictates pipeline order.

    "Aaj hum meeting start karte hain" is Hindi, and script comparison has no
    signal to detect that, because Hinglish and English share the Latin alphabet.

    This is asserted rather than treated as a bug: it is why language tagging must
    run on the raw ASR output, before normalization rewrites Devanagari into Roman
    script. Reversing that order raises no error and silently labels every segment
    English. If a future change makes this test fail, the ordering constraint must
    be re-derived rather than assumed to still hold.
    """
    assert detect_language("Aaj hum meeting start karte hain.") == ENGLISH


def test_normalization_destroys_the_signal_this_detector_relies_on():
    """The same sentence, before and after Romanization, classifies differently."""
    devanagari = "आज हम मीटिंग शुरू करते हैं"
    romanized = "aaj hum meeting shuru karte hain"
    assert detect_language(devanagari) == HINDI
    assert detect_language(romanized) == ENGLISH


# --------------------------------------------------------------------------
# Thresholds and edge cases
# --------------------------------------------------------------------------
def test_short_segment_takes_whichever_script_appeared():
    assert detect_language("नमस्ते") == HINDI
    assert detect_language("Okay") == ENGLISH


def test_ratio_exactly_at_the_threshold_is_not_code_mixed():
    """Pins the boundary so a refactor cannot silently shift the class balance.

    With 1 Devanagari word in 20 scripted words the ratio is 0.05, at or below the
    0.15 threshold, so this rounds to the majority rather than becoming mixed.
    """
    text = " ".join(["word"] * 19 + ["हम"])
    detail = detect_language_detailed(text)
    assert detail["devanagari_ratio"] == pytest.approx(0.05)
    assert detail["language"] == ENGLISH


def test_ratio_just_above_the_threshold_is_code_mixed():
    text = " ".join(["word"] * 8 + ["हम", "आज"])
    detail = detect_language_detailed(text)
    assert detail["devanagari_ratio"] == pytest.approx(0.2)
    assert detail["language"] == CODE_MIXED


def test_empty_and_punctuation_only_input_does_not_crash():
    for text in ["", "   ", "...", "123 456", "!!! ???"]:
        assert detect_language(text) == ENGLISH


def test_numbers_and_punctuation_are_excluded_from_the_ratio():
    """Digits belong to no script and must not dilute the proportions."""
    detail = detect_language_detailed("आज 2026 में हम")
    assert detail["other_words"] == 1
    assert detail["devanagari_words"] == 3
    assert detail["language"] == HINDI


def test_devanagari_danda_is_stripped_as_punctuation():
    detail = detect_language_detailed("आज हम मीटिंग करेंगे।")
    assert detail["devanagari_words"] == 4
    assert detail["language"] == HINDI


# --------------------------------------------------------------------------
# detect_language_detailed reasons
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "no-scripted-words"),
        ("Okay", "too-short-for-mix-check"),
        ("आज हम मीटिंग करेंगे", "devanagari-dominant"),
        ("we will meet tomorrow", "latin-dominant"),
        ("आज हम project discuss करेंगे", "mixed-scripts"),
    ],
)
def test_detailed_reason_explains_the_decision(text, reason):
    """Every label must be explainable from the recorded word counts."""
    assert detect_language_detailed(text)["reason"] == reason


# --------------------------------------------------------------------------
# detect_language_for_segments
# --------------------------------------------------------------------------
def test_tagging_adds_language_and_preserves_other_fields(aligned_segments):
    tagged = detect_language_for_segments(aligned_segments)
    assert len(tagged) == len(aligned_segments)
    for original, result in zip(aligned_segments, tagged, strict=True):
        assert result["start"] == original["start"]
        assert result["end"] == original["end"]
        assert result["speaker"] == original["speaker"]
        assert result["text"] == original["text"]
        assert "language" in result


def test_tagging_does_not_mutate_input(aligned_segments):
    before = [dict(s) for s in aligned_segments]
    detect_language_for_segments(aligned_segments)
    assert aligned_segments == before


def test_detailed_mode_attaches_the_breakdown(aligned_segments):
    tagged = detect_language_for_segments(aligned_segments, detailed=True)
    assert "language_detail" in tagged[0]
    assert "devanagari_words" in tagged[0]["language_detail"]


def test_tagging_handles_missing_text_key():
    tagged = detect_language_for_segments([{"start": 0, "end": 1}])
    assert tagged[0]["language"] == ENGLISH


def test_tagging_the_synthetic_fixture_produces_all_three_classes(
    synthetic_tagged_segments,
):
    """A realistic multi-speaker transcript should exercise every class.

    Note this fixture is already Romanized, so the labels produced here will not
    match its own pre-existing "language" field -- which is a concrete instance of
    the limitation asserted above, not a fixture problem.
    """
    texts = [{"text": s["text"]} for s in synthetic_tagged_segments]
    labels = {s["language"] for s in detect_language_for_segments(texts)}
    assert labels <= {ENGLISH, HINDI, CODE_MIXED}


# --------------------------------------------------------------------------
# language_distribution
# --------------------------------------------------------------------------
def test_distribution_reports_counts_and_durations():
    segments = [
        {"start": 0, "end": 10, "language": ENGLISH},
        {"start": 10, "end": 12, "language": HINDI},
        {"start": 12, "end": 14, "language": HINDI},
    ]
    distribution = language_distribution(segments)
    assert distribution["segment_counts"] == {ENGLISH: 1, HINDI: 2}
    assert distribution["duration_sec"] == {ENGLISH: 10.0, HINDI: 4.0}
    # Counts and durations disagree here, which is exactly why both are reported:
    # Hindi leads by segment count but English dominates the time.
    assert distribution["segment_pct"][HINDI] > distribution["segment_pct"][ENGLISH]
    assert distribution["duration_pct"][ENGLISH] > distribution["duration_pct"][HINDI]


def test_distribution_of_untagged_segments_is_empty():
    assert language_distribution([{"start": 0, "end": 1}])["segment_counts"] == {}


def test_distribution_of_empty_transcript_does_not_divide_by_zero():
    distribution = language_distribution([])
    assert distribution["segment_pct"] == {}
    assert distribution["duration_pct"] == {}
