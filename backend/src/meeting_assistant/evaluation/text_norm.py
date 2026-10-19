"""Shared text normalization for cross-transcript comparison (WER/CER/ROUGE).

Every metric in this package that compares two strings — a hypothesis against
a reference — goes through :func:`normalize_text` first, and only through
this one function, so "does capitalization count as an error" or "does a
comma count as a word" is answered identically everywhere a comparison
happens rather than drifting between metric implementations.

The policy: Unicode NFKC normalization, zero-width characters stripped,
Devanagari digits mapped to ASCII, Latin text lowercased (Devanagari has no
case, so this is a no-op there), and punctuation stripped except an
apostrophe or hyphen sitting directly between two word characters — so
``"don't"`` and ``"kya-baat"`` survive intact while a sentence-leading or
trailing ``-``/``'`` does not.

**Word characters are decided by Unicode category, not by Python's regex
``\\w``.** That distinction is the reason this module exists rather than being
three lines of ``re.sub``: ``\\w`` matches letters and digits but not Unicode
category Mn/Mc (combining marks), and Devanagari vowel signs (matras) and the
virama are exactly those categories. A first version of this function used
``[^\\w\\s'-]`` to strip punctuation and, on real Hindi text, silently deleted
the matras along with it — ``"मीटिंग"`` came out as ``"म ट ग"``. That is not a
cosmetic bug: it would have corrupted every Hindi CER number in a published
result, and corrupted the input to the romanization step used for
``WER_romanized`` even worse, since transliterating already-mangled Devanagari
produces meaningless Roman output. Iterating characters and checking
``unicodedata.category`` explicitly is what keeps combining marks intact.
"""

from __future__ import annotations

import re
import unicodedata

_ZERO_WIDTH_CHARS = frozenset("​‌‍﻿")
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_WHITESPACE_RE = re.compile(r"\s+")

# A conservative starter list of fillers common in this project's code-mixed
# recordings. Off by default: stripping fillers changes what a WER number
# means, so it must be an explicit, visible choice (and is itself a
# documented ablation -- "how sensitive is the headline number to filler
# words") rather than baked silently into the default policy.
DEFAULT_FILLERS = frozenset(
    {"um", "uh", "umm", "uhh", "hmm", "matlab", "like", "actually", "basically", "haan", "toh",
     # Hesitation sounds as transcribed in published corpora (DISPLACE writes
     # them in both scripts); this project's own guide leaves them out.
     "ahh", "ah", "aa", "hm", "mm", "uhm", "अ", "आ", "हम्म", "उम"}
)


def _is_word_char(ch: str) -> bool:
    """Letters, digits, and combining marks (matras, virama, nukta).

    Combining marks must count as word characters: they attach to the letter
    before them and carry meaning (a vowel, a conjunct) rather than being
    decoration, so stripping them the way punctuation is stripped would
    silently change the word rather than merely cleaning its boundary.
    """
    category = unicodedata.category(ch)
    return category[0] in ("L", "N") or category in ("Mn", "Mc")


def normalize_text(text: str, *, strip_fillers: bool = False) -> str:
    """Canonicalize ``text`` under this project's WER/CER comparison policy.

    Args:
        strip_fillers: also remove words in :data:`DEFAULT_FILLERS`. Reported
            as a separate, explicitly-labelled number alongside the default
            policy's WER, never silently substituted for it.

    Returns:
        The normalized text. Idempotent: normalizing an already-normalized
        string returns it unchanged.
    """
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if ch not in _ZERO_WIDTH_CHARS)
    text = text.translate(_DEVANAGARI_DIGITS)
    text = text.lower()

    kept: list[str] = []
    for i, ch in enumerate(text):
        if _is_word_char(ch):
            kept.append(ch)
        elif ch in ("'", "-"):
            prev_word = i > 0 and _is_word_char(text[i - 1])
            next_word = i + 1 < len(text) and _is_word_char(text[i + 1])
            kept.append(ch if (prev_word and next_word) else " ")
        else:
            kept.append(" ")

    normalized = _WHITESPACE_RE.sub(" ", "".join(kept)).strip()

    if strip_fillers:
        words = [w for w in normalized.split(" ") if w not in DEFAULT_FILLERS]
        normalized = " ".join(words)

    return normalized
