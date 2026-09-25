"""ASR accuracy: word and character error rate, with the Hinglish
cross-script policy stated up front rather than left implicit in a number.

A code-mixed transcript can legitimately render a Hindi word two ways: as
Devanagari (what Whisper actually emits) or as Latin script (what this
project's normalization stage produces). Comparing a Devanagari hypothesis
against a Romanized reference — or vice versa — makes every correctly
transcribed Hindi word look like a total substitution, which inflates WER
toward 100% on exactly the words this project cares most about getting right.
That is a scoring artifact, not an ASR failure, and reporting it as one would
misrepresent the actual result.

The policy is therefore to report **three numbers per clip**, computed by
:func:`word_error_rate`, :func:`romanized_word_error_rate` and
:func:`character_error_rate` respectively:

``WER_raw`` — hypothesis and reference compared in whatever script each
happens to use. Measures ASR alone, script differences included, and is
directly comparable to WER numbers reported for monolingual systems.

``WER_romanized`` — both sides deterministically transliterated to ITRANS via
``indic_transliteration`` before comparison, removing the script mismatch so
Hindi and English contributions become comparable. Never uses this project's
own Ollama-based normalizer for that transliteration: scoring the system
under test with a reference the same system helped produce is circular, and
would inflate accuracy on exactly the segments normalization handles well
while hiding the ones it does not.

``CER_raw`` — character error rate on the untransliterated text. More
informative than WER for morphologically rich Hindi (where a single wrong
vowel sign changes the word but not much of the string) and for the spelling
variance casual Romanized Hindi has no fixed convention for ("kya" vs "kyaa").

All three route every string through
:mod:`meeting_assistant.evaluation.text_norm` first, so casing, punctuation
and digit-script differences are never counted as transcription errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jiwer

from meeting_assistant.evaluation.text_norm import normalize_text


@dataclass
class WordErrorResult:
    """WER plus its substitution/deletion/insertion breakdown.

    The breakdown is kept, not just the headline ratio, because a WER of 0.3
    made entirely of substitutions describes a different system than one made
    entirely of insertions (Whisper hallucinating words over silence,
    typically) -- collapsing them to one number would discard that.
    """

    wer: float
    substitutions: int
    deletions: int
    insertions: int
    hits: int
    reference_words: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "wer": round(self.wer, 4),
            "substitutions": self.substitutions,
            "deletions": self.deletions,
            "insertions": self.insertions,
            "hits": self.hits,
            "reference_words": self.reference_words,
        }


@dataclass
class CharErrorResult:
    cer: float
    reference_chars: int

    def as_dict(self) -> dict[str, Any]:
        return {"cer": round(self.cer, 4), "reference_chars": self.reference_chars}


def word_error_rate(reference: str, hypothesis: str) -> WordErrorResult:
    """WER over :func:`~meeting_assistant.evaluation.text_norm.normalize_text`-d text.

    An empty (post-normalization) reference is a degenerate case ``jiwer``
    raises on rather than scores. Handled explicitly: 0.0 if the hypothesis is
    also empty (nothing said, nothing transcribed -- perfect agreement), 1.0
    otherwise (every hypothesis word is an insertion against nothing).
    """
    ref = normalize_text(reference)
    hyp = normalize_text(hypothesis)

    if not ref:
        hyp_words = hyp.split() if hyp else []
        return WordErrorResult(
            wer=(0.0 if not hyp_words else 1.0),
            substitutions=0,
            deletions=0,
            insertions=len(hyp_words),
            hits=0,
            reference_words=0,
        )

    out = jiwer.process_words([ref], [hyp])
    return WordErrorResult(
        wer=out.wer,
        substitutions=out.substitutions,
        deletions=out.deletions,
        insertions=out.insertions,
        hits=out.hits,
        reference_words=out.hits + out.substitutions + out.deletions,
    )


def character_error_rate(reference: str, hypothesis: str) -> CharErrorResult:
    """CER over normalized text. Same empty-reference handling as WER."""
    ref = normalize_text(reference)
    hyp = normalize_text(hypothesis)

    if not ref:
        return CharErrorResult(cer=(0.0 if not hyp else 1.0), reference_chars=0)

    out = jiwer.process_characters([ref], [hyp])
    return CharErrorResult(cer=out.cer, reference_chars=len(ref.replace(" ", "")))


def _romanize(text: str) -> str:
    """Deterministic Devanagari -> ITRANS transliteration.

    Latin-script text passes through unchanged (verified against real
    code-mixed sentences during development): only characters the scheme
    recognizes as Devanagari are converted, so this is safe to apply
    uniformly regardless of how much of a segment is actually Hindi.
    """
    from indic_transliteration import sanscript

    return sanscript.transliterate(text, sanscript.DEVANAGARI, sanscript.ITRANS)


def romanized_word_error_rate(reference: str, hypothesis: str) -> WordErrorResult:
    """WER after transliterating both reference and hypothesis to ITRANS.

    See the module docstring for why this exists and why it must never be
    computed using this project's own normalizer as the transliteration step.
    """
    return word_error_rate(_romanize(reference), _romanize(hypothesis))
