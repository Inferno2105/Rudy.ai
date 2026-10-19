"""Reading a clip's hand-made reference labels from disk.

One folder per evaluation clip, ``data/eval/references/<clip_id>/``, matching
the recording ``data/audio/<clip_id>.wav``. Annotators write plain files they
can produce without any tooling (``docs/annotation-guide.md`` explains each):

=====================  ========================================================
``transcript.txt``     What was said, each word in the script it was spoken in.
``turns.txt``          Audacity label export: one ``start<TAB>end<TAB>speaker``
                       line per speaker turn.
``languages.txt``      Audacity label export: one ``start<TAB>end<TAB>language``
                       line per stretch of speech in one language mode.
``languages_b.txt``    The second annotator's labels for the same stretches
                       (inter-annotator agreement); optional.
``summary.txt``        A few sentences on what the meeting was about.
``action_items.txt``   One ``person | task | deadline`` line per commitment,
                       or the single word ``none``.
``meta.json``          Recording condition, speakers, device, date, consent ids.
=====================  ========================================================

Lines starting with ``#`` in the text files are instructions left by the
templates and are ignored. Earlier formats (``turns.rttm``,
``action_items.json``) are still read.

**Language and speaker labels are given by time, not per system segment.** A
label attached to "segment 7 of run X" is tied to how that one run cut the
audio, so a configuration that segments differently (another Whisper model)
could not be scored against it, and labelling next to the system's own guess
biases the labeller towards agreeing with it. Time-based labels are written
once, without seeing any system output, and each system segment is matched to
the reference label that overlaps it the longest (:func:`label_at`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from meeting_assistant.language.detection import CODE_MIXED, ENGLISH, HINDI

LANGUAGES = (HINDI, ENGLISH, CODE_MIXED)
# What annotators may type in Audacity; case-insensitive.
_LANGUAGE_ALIASES = {
    "h": HINDI,
    "hi": HINDI,
    "hindi": HINDI,
    "e": ENGLISH,
    "en": ENGLISH,
    "english": ENGLISH,
    "m": CODE_MIXED,
    "mix": CODE_MIXED,
    "mixed": CODE_MIXED,
    "code-mixed": CODE_MIXED,
    "codemixed": CODE_MIXED,
}

CONDITIONS = ("hindi-dominant", "english-dominant", "code-mixed", "adverse")
NO_ACTION_ITEMS = "none"
# The label each stretch carries in a blind copy, until the second annotator replaces it.
BLIND_PLACEHOLDER = "?"


class LabelError(ValueError):
    """A label file that cannot be read, with the file and line it is on."""


def normalize_language(label: str) -> str | None:
    """The canonical language for an annotator's label, or ``None`` if unknown."""
    return _LANGUAGE_ALIASES.get(label.strip().lower())


def _content_lines(path: Path) -> list[tuple[int, str]]:
    """``(line number, text)`` of every non-blank line that is not a ``#`` comment."""
    lines = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if line.strip() and not line.lstrip().startswith("#"):
            lines.append((number, line))
    return lines


def read_text_label(path: Path) -> str | None:
    """A free-text label (transcript, summary) without template comments, or
    ``None`` if the file is missing or still empty."""
    if not path.is_file():
        return None
    text = "\n".join(line for _, line in _content_lines(path)).strip()
    return text or None


def read_label_track(path: Path) -> list[dict[str, Any]]:
    """An Audacity label export as ``[{"start", "end", "label"}]``.

    Audacity writes ``start<TAB>end<TAB>label``; a point label (start == end)
    or a label with no text is an annotation mistake and is reported.
    """
    spans = []
    for number, line in _content_lines(path):
        parts = line.split("\t")
        if len(parts) < 3:
            raise LabelError(
                f"{path.name} line {number}: expected start<TAB>end<TAB>label "
                f"(an Audacity label export), got {line.strip()!r}"
            )
        try:
            start, end = float(parts[0]), float(parts[1])
        except ValueError as exc:
            raise LabelError(f"{path.name} line {number}: times must be numbers") from exc
        label = parts[2].strip()
        if not label:
            raise LabelError(f"{path.name} line {number}: the label has no text")
        if end <= start:
            raise LabelError(
                f"{path.name} line {number}: ends at {end:.2f}s, not after its start "
                f"({start:.2f}s); drag the label across a region instead of clicking a point"
            )
        spans.append({"start": round(start, 3), "end": round(end, 3), "label": label})
    return sorted(spans, key=lambda span: span["start"])


def read_language_spans(path: Path) -> list[dict[str, Any]]:
    """``languages.txt`` as ``[{"start", "end", "language"}]`` with canonical names."""
    spans = []
    for span in read_label_track(path):
        language = normalize_language(span["label"])
        if span["label"] == BLIND_PLACEHOLDER:
            raise LabelError(
                f"{path.name}: the stretch at {span['start']:.2f}s is not labelled yet "
                f"(still '{BLIND_PLACEHOLDER}')"
            )
        if language is None:
            raise LabelError(
                f"{path.name}: {span['label']!r} at {span['start']:.2f}s is not a language "
                "label; use Hindi, English or Code-Mixed (or H, E, M)"
            )
        spans.append({"start": span["start"], "end": span["end"], "language": language})
    return spans


def read_turns(clip_dir: Path) -> list[dict[str, Any]] | None:
    """Speaker turns as ``[{"start", "end", "speaker"}]``: ``turns.txt``, else ``turns.rttm``."""
    if (clip_dir / "turns.txt").is_file():
        return [
            {"start": s["start"], "end": s["end"], "speaker": s["label"]}
            for s in read_label_track(clip_dir / "turns.txt")
        ]
    if (clip_dir / "turns.rttm").is_file():
        from meeting_assistant.evaluation.rttm import read_rttm

        return read_rttm(clip_dir / "turns.rttm")
    return None


def read_action_items(clip_dir: Path) -> list[dict[str, Any]] | None:
    """``action_items.txt`` (``person | task | deadline`` per line, ``-`` for
    unknown), else ``action_items.json``; ``None`` if not written yet."""
    path = clip_dir / "action_items.txt"
    if path.is_file():
        lines = _content_lines(path)
        if not lines:
            return None
        if len(lines) == 1 and lines[0][1].strip().lower() == NO_ACTION_ITEMS:
            return []
        items = []
        for number, line in lines:
            parts = [part.strip() for part in line.split("|")]
            if len(parts) != 3:
                raise LabelError(
                    f"action_items.txt line {number}: expected 'person | task | deadline' "
                    f"(use - for an unknown person or deadline), got {line.strip()!r}"
                )
            person, task, deadline = (None if part in ("", "-") else part for part in parts)
            if task is None:
                raise LabelError(f"action_items.txt line {number}: the task is empty")
            items.append({"person": person, "task": task, "deadline": deadline})
        return items
    if (clip_dir / "action_items.json").is_file():
        return json.loads((clip_dir / "action_items.json").read_text(encoding="utf-8"))
    return None


def read_meta(clip_dir: Path) -> dict[str, Any]:
    path = clip_dir / "meta.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LabelError(f"meta.json is not valid JSON: {exc.msg} (line {exc.lineno})") from exc


def label_at(start: float, end: float, spans: list[dict[str, Any]], key: str) -> Any:
    """The ``key`` of the span overlapping ``[start, end)`` the longest, or ``None``."""
    best, best_overlap = None, 0.0
    for span in spans:
        overlap = min(end, span["end"]) - max(start, span["start"])
        if overlap > best_overlap:
            best, best_overlap = span[key], overlap
    return best


def language_at(start: float, end: float, spans: list[dict[str, Any]]) -> str | None:
    """The reference language of the stretch ``[start, end)``, from what it contains.

    A system segment is often longer than one reference label: DISPLACE labels
    language every few words, and an annotator's stretch can end mid-segment.
    Taking the single longest-overlapping label would call a segment holding a
    real Hindi-English switch purely Hindi, so the truth is decided by the
    time each language takes up inside the segment, with the same threshold the
    detector uses for words (``CODE_MIX_THRESHOLD``): Code-Mixed when labelled
    Code-Mixed speech dominates, or when the lesser of Hindi and English is at
    least that share of the labelled time; otherwise the larger of the two.
    ``None`` when no label overlaps the stretch.
    """
    from meeting_assistant.language.detection import CODE_MIX_THRESHOLD

    seconds = dict.fromkeys(LANGUAGES, 0.0)
    for span in spans:
        overlap = min(end, span["end"]) - max(start, span["start"])
        if overlap > 0:
            seconds[span["language"]] += overlap
    total = sum(seconds.values())
    if total <= 0:
        return None
    hindi, english, mixed = seconds[HINDI], seconds[ENGLISH], seconds[CODE_MIXED]
    if mixed >= max(hindi, english) or min(hindi, english) / total >= CODE_MIX_THRESHOLD:
        return CODE_MIXED
    return HINDI if hindi >= english else ENGLISH


@dataclass
class ClipLabels:
    """Everything an annotator wrote for one clip; each part ``None`` until written."""

    transcript: str | None = None
    turns: list[dict[str, Any]] | None = None
    language_spans: list[dict[str, Any]] | None = None
    second_language_spans: list[dict[str, Any]] | None = None
    summary: str | None = None
    action_items: list[dict[str, Any]] | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def read_clip(clip_dir: Path) -> ClipLabels:
    """Read every label of a clip. Raises :class:`LabelError` on a malformed file."""
    def spans(name: str) -> list[dict[str, Any]] | None:
        path = clip_dir / name
        return read_language_spans(path) if path.is_file() and _content_lines(path) else None

    return ClipLabels(
        transcript=read_text_label(clip_dir / "transcript.txt"),
        turns=read_turns(clip_dir),
        language_spans=spans("languages.txt"),
        second_language_spans=spans("languages_b.txt"),
        summary=read_text_label(clip_dir / "summary.txt"),
        action_items=read_action_items(clip_dir),
        meta=read_meta(clip_dir),
    )


def paired_language_labels(
    first: list[dict[str, Any]], second: list[dict[str, Any]]
) -> list[tuple[str, str]]:
    """The two annotators' labels for each shared stretch, for Cohen's kappa.

    The second annotator labels a copy of the first annotator's stretches with
    the labels removed (``meeting-assistant dataset blind-copy``), so stretches
    pair up by their times.
    """
    by_time = {(round(s["start"], 2), round(s["end"], 2)): s["language"] for s in first}
    pairs = []
    for span in second:
        key = (round(span["start"], 2), round(span["end"], 2))
        if key in by_time:
            pairs.append((by_time[key], span["language"]))
    return pairs
