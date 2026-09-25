"""Classify a transcript segment as English, Hindi, or code-mixed.

Method: word-level Unicode script classification. Each word is Devanagari
(U+0900-U+097F), Latin, or neither; the segment is labelled by the proportions.
This is a rule-based heuristic, not a trained classifier, chosen because it is
deterministic, instant, needs no model or network, and — most usefully when
explaining a result — can justify any single decision by showing the word split
that produced it.

**The limitation that dictates pipeline order.** Script comparison cannot
distinguish Romanized Hindi from English, because both are written in Latin
script. "Aaj hum meeting start karte hain" is Hindi, and this module will call it
English. There is no signal available to do otherwise.

The consequence is an ordering constraint: language tagging must run on the raw
ASR output, while Devanagari is still present, and *before* the Hinglish
normalization stage rewrites it into Roman script. Running them the other way
round produces no error — it silently labels every segment English, and every
downstream language statistic becomes meaningless. The pipeline enforces the
order through stage dependencies rather than relying on anyone remembering it.

This limitation is a reportable property of the method, not a defect to hide: it
is measured directly in the evaluation, by comparing accuracy on raw versus
normalized transcripts.

Extending beyond it would mean a different method — a Hinglish lexicon, character
n-grams, or a small language-ID model — which is a deliberate future direction
rather than a tweak to this one.
"""

from __future__ import annotations

import re
from typing import Any

ENGLISH = "English"
HINDI = "Hindi"
CODE_MIXED = "Code-Mixed"

DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
LATIN_RE = re.compile(r"[A-Za-z]")

# Below this many script-bearing words, proportions are noise: a one-word "Okay"
# is not meaningfully mixed or unmixed, so the segment takes whichever script
# appeared instead of being forced through the ratio test.
MIN_WORDS_FOR_MIX_CHECK = 2

# A segment is code-mixed once the minority script reaches this share of its
# words. At 0.15, a single English technical term in an otherwise Hindi sentence
# does not flip the label, but a genuine mixture does. Code-mixing in these
# meetings is mostly at this granularity — Hindi grammar carrying English nouns —
# so the threshold decides how much borrowing counts as mixing. It is swept in
# the evaluation rather than asserted.
CODE_MIX_THRESHOLD = 0.15

_PUNCTUATION = "\"'.,!?;:()[]{}<>-–—…।॥"  # includes danda and double danda


def classify_word(word: str) -> str:
    """Classify one word as ``devanagari``, ``latin``, or ``other``.

    Devanagari is checked first so a word mixing scripts (an inflected English
    loanword, say) counts as Devanagari — the Devanagari portion is the stronger
    signal that the surrounding language is Hindi.
    """
    if DEVANAGARI_RE.search(word):
        return "devanagari"
    if LATIN_RE.search(word):
        return "latin"
    return "other"


def _tokenize(text: str) -> list[str]:
    """Split on whitespace and strip surrounding punctuation."""
    words = (word.strip(_PUNCTUATION) for word in text.split())
    return [word for word in words if word]


def detect_language_detailed(text: str) -> dict[str, Any]:
    """Classify ``text`` and report the counts behind the decision.

    The breakdown is returned because it is what makes a label defensible. When a
    segment's classification looks wrong, the answer is almost always visible in
    the word counts, and having them recorded avoids re-deriving the split by
    hand.

    Returns:
        ``language`` plus ``devanagari_words``, ``latin_words``, ``other_words``,
        ``devanagari_ratio`` and ``reason``.
    """
    words = _tokenize(text)

    devanagari = sum(1 for word in words if classify_word(word) == "devanagari")
    latin = sum(1 for word in words if classify_word(word) == "latin")
    other = len(words) - devanagari - latin
    scripted = devanagari + latin

    base = {
        "devanagari_words": devanagari,
        "latin_words": latin,
        "other_words": other,
    }

    # No script-bearing words at all: empty text, or purely numeric/punctuation.
    # Defaulting to English is arbitrary, and labelled as such rather than
    # dressed up as a decision.
    if scripted == 0:
        return {**base, "language": ENGLISH, "devanagari_ratio": 0.0, "reason": "no-scripted-words"}

    devanagari_ratio = devanagari / scripted

    if scripted < MIN_WORDS_FOR_MIX_CHECK:
        language = HINDI if devanagari > 0 else ENGLISH
        return {
            **base,
            "language": language,
            "devanagari_ratio": round(devanagari_ratio, 4),
            "reason": "too-short-for-mix-check",
        }

    if devanagari_ratio >= 1 - CODE_MIX_THRESHOLD:
        language, reason = HINDI, "devanagari-dominant"
    elif devanagari_ratio <= CODE_MIX_THRESHOLD:
        language, reason = ENGLISH, "latin-dominant"
    else:
        language, reason = CODE_MIXED, "mixed-scripts"

    return {
        **base,
        "language": language,
        "devanagari_ratio": round(devanagari_ratio, 4),
        "reason": reason,
    }


def detect_language(text: str) -> str:
    """Classify ``text`` as :data:`ENGLISH`, :data:`HINDI` or :data:`CODE_MIXED`."""
    return detect_language_detailed(text)["language"]


def detect_language_for_segments(
    segments: list[dict[str, Any]],
    *,
    detailed: bool = False,
) -> list[dict[str, Any]]:
    """Add a ``language`` field to every segment, leaving all else untouched.

    Args:
        detailed: also attach ``language_detail`` with the word counts. Off by
            default to keep the artifact readable; on when analysing
            classification behaviour.

    Returns a new list; the inputs are not modified.
    """
    tagged: list[dict[str, Any]] = []
    for segment in segments:
        result = detect_language_detailed(segment.get("text", ""))
        new_segment = dict(segment)
        new_segment["language"] = result["language"]
        if detailed:
            new_segment["language_detail"] = result
        tagged.append(new_segment)
    return tagged


def language_distribution(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise language use across a transcript, for the run manifest.

    Reports shares by both segment count and duration, since a few long Hindi
    turns and many short English interjections describe very different meetings
    while giving similar segment counts.
    """
    counts: dict[str, int] = {}
    durations: dict[str, float] = {}

    for segment in segments:
        language = segment.get("language")
        if not language:
            continue
        counts[language] = counts.get(language, 0) + 1
        durations[language] = durations.get(language, 0.0) + max(
            0.0, segment.get("end", 0.0) - segment.get("start", 0.0)
        )

    total_count = sum(counts.values())
    total_duration = sum(durations.values())

    return {
        "segment_counts": counts,
        "segment_pct": {
            language: round(100.0 * n / total_count, 2) for language, n in counts.items()
        }
        if total_count
        else {},
        "duration_sec": {language: round(d, 2) for language, d in durations.items()},
        "duration_pct": {
            language: round(100.0 * d / total_duration, 2) for language, d in durations.items()
        }
        if total_duration
        else {},
    }
