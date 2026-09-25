"""Extract JSON from a language model's reply.

Local instruction-tuned models wrap JSON in markdown fences, prefix it with
"Here is the JSON you requested:", or append a closing remark — reliably enough
that treating the reply as parseable JSON fails often, and reliably enough that
recovering the object is straightforward. This module does the recovery in one
place so every caller behaves identically.

It is public, unlike its predecessor. The previous version was a private
``_extract_json`` inside the summarization module, which the action-item module
then imported across module boundaries — a name with a leading underscore being
used as shared API, which meant neither module could be refactored safely.
"""

from __future__ import annotations

import json
import re
from typing import Any

from meeting_assistant.errors import LLMError

_FENCE_OPEN = re.compile(r"^\s*```(?:json|JSON)?\s*", re.MULTILINE)
_FENCE_CLOSE = re.compile(r"\s*```\s*$", re.MULTILINE)


def _find_balanced_span(text: str, open_ch: str, close_ch: str) -> str | None:
    """Return the first balanced ``open_ch``/``close_ch`` span in ``text``.

    Brace counting is string-aware: a greedy ``\\{.*\\}`` regex breaks as soon as
    a value legitimately contains a brace, and for this project that is not
    hypothetical — transcript text quoted back inside a summary or an action item
    can contain anything the speakers said.
    """
    start = text.find(open_ch)
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(text)):
        char = text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == open_ch:
            depth += 1
        elif char == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    return None


def extract_json(raw: str, *, expect: type = dict) -> Any:
    """Parse the first JSON value out of a model reply.

    Args:
        raw: the model's reply, in whatever shape it arrived.
        expect: the expected top-level type, ``dict`` or ``list``.

    Returns:
        The parsed value.

    Raises:
        LLMError: if no value of the expected type could be parsed. The message
            includes a snippet of the raw reply, because a malformed response is
            almost always diagnosed by reading what the model actually said.
    """
    if not raw or not raw.strip():
        raise LLMError("Model returned an empty response.")

    cleaned = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", raw.strip())).strip()

    # Fast path: the model did as it was told.
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = None

    if parsed is None:
        open_ch, close_ch = ("[", "]") if expect is list else ("{", "}")
        span = _find_balanced_span(cleaned, open_ch, close_ch)
        if span is None:
            raise LLMError(
                f"Model response contained no JSON {expect.__name__}. "
                f"Raw response: {raw[:400]!r}"
            )
        try:
            parsed = json.loads(span)
        except json.JSONDecodeError as exc:
            raise LLMError(
                f"Model response was not valid JSON ({exc}). Raw response: {raw[:400]!r}"
            ) from exc

    if not isinstance(parsed, expect):
        raise LLMError(
            f"Expected a JSON {expect.__name__} but got {type(parsed).__name__}. "
            f"Raw response: {raw[:400]!r}"
        )

    return parsed
