"""Creating, checking and preparing the evaluation dataset's label folders.

Behind ``meeting-assistant dataset new|check|blind-copy``. The check exists so
labelling mistakes surface the day they are made, not when the paper's tables
come out wrong: every file is parsed exactly as the evaluation will parse it
(:mod:`meeting_assistant.evaluation.references`), and checked against the
recording it describes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from meeting_assistant import config
from meeting_assistant.evaluation.references import (
    BLIND_PLACEHOLDER,
    CONDITIONS,
    LabelError,
    read_action_items,
    read_language_spans,
    read_meta,
    read_text_label,
    read_turns,
)
from meeting_assistant.io_utils import write_json, write_text

CLIP_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
CONSENT_ID = re.compile(r"^P\d{2,3}$")
# Labels may run this far past the end of the recording (Audacity rounding).
_END_SLACK_SEC = 0.5
# Two language labels may overlap this much before it counts as a mistake.
_OVERLAP_SLACK_SEC = 0.05

ITEMS = ("audio", "transcript", "turns", "languages", "summary", "actions", "meta")
OK, MISSING, PROBLEM = "ok", "--", "ERR"
# A label a published corpus does not have (DISPLACE has no summaries).
NOT_APPLICABLE = "n/a"


def references_dir() -> Path:
    return config.EVAL_DIR / "references"


def audio_path(clip_id: str) -> Path:
    return config.AUDIO_DIR / f"{clip_id}.wav"


# ---------------------------------------------------------------------------
# dataset new
# ---------------------------------------------------------------------------
_TRANSCRIPT_TEMPLATE = """\
# Reference transcript for {clip}. Lines starting with # are ignored.
# Write exactly what was said, in the order it was said, each word in the script
# it was spoken in: Devanagari for Hindi words, Latin letters for English words.
# Do not translate, tidy up or correct grammar. Numbers as words, as spoken.
# Full rules: docs/annotation-guide.md, step 2.
"""

_SUMMARY_TEMPLATE = """\
# Reference summary for {clip}. Lines starting with # are ignored.
# 3-5 sentences: what the meeting was about and what was decided.
# Write it from your transcript BEFORE you look at the app's summary of this clip.
# Full rules: docs/annotation-guide.md, step 5.
"""

_ACTIONS_TEMPLATE = """\
# Action items for {clip}. Lines starting with # are ignored.
# One line per commitment someone made:   person | task | deadline
# Use - when the person or the deadline was not said. Examples:
#   Riya | send the test report to the team | Friday
#   - | book the meeting room | -
# If nobody committed to anything, write the single word: none
# Full rules: docs/annotation-guide.md, step 6.
"""


def new_clip(clip_id: str) -> tuple[Path, list[str]]:
    """Create ``references/<clip_id>/`` with templates; return it and any notes.

    Raises:
        ValueError: the id is not a valid clip id, or the folder already exists.
    """
    if not CLIP_ID.match(clip_id):
        raise ValueError(
            f"{clip_id!r} is not a valid clip id: use lowercase letters, digits, - and _ "
            "(for example clip01)"
        )
    folder = references_dir() / clip_id
    if folder.exists():
        raise ValueError(f"{folder} already exists; nothing was changed")
    folder.mkdir(parents=True)
    write_text(folder / "transcript.txt", _TRANSCRIPT_TEMPLATE.format(clip=clip_id))
    write_text(folder / "summary.txt", _SUMMARY_TEMPLATE.format(clip=clip_id))
    write_text(folder / "action_items.txt", _ACTIONS_TEMPLATE.format(clip=clip_id))
    write_json(
        folder / "meta.json",
        {
            "condition": "",
            "speakers": 0,
            "device": "",
            "recorded_on": "",
            "participants": [],
            "notes": "",
        },
    )
    notes = []
    if not audio_path(clip_id).is_file():
        notes.append(f"No recording yet at {audio_path(clip_id)}; save it there before labelling.")
    return folder, notes


# ---------------------------------------------------------------------------
# dataset blind-copy
# ---------------------------------------------------------------------------
def blind_copy(clip_id: str) -> tuple[Path, int]:
    """Write ``languages_b.txt``: the first annotator's stretches, labels removed.

    The second annotator imports it into Audacity and labels each stretch
    without seeing the first labels, so the two can be compared stretch by
    stretch (Cohen's kappa).
    """
    folder = references_dir() / clip_id
    first = folder / "languages.txt"
    if not first.is_file():
        raise ValueError(f"{first} does not exist yet; the first annotator labels languages first")
    spans = read_language_spans(first)
    target = folder / "languages_b.txt"
    if target.exists():
        raise ValueError(f"{target} already exists; delete it first to start over")
    lines = [f"{s['start']:.6f}\t{s['end']:.6f}\t{BLIND_PLACEHOLDER}" for s in spans]
    write_text(target, "\n".join(lines) + "\n")
    return target, len(spans)


# ---------------------------------------------------------------------------
# dataset check
# ---------------------------------------------------------------------------
@dataclass
class ClipCheck:
    clip_id: str
    duration: float | None = None
    status: dict[str, str] = field(default_factory=lambda: dict.fromkeys(ITEMS, MISSING))
    second_annotator: str = MISSING
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return all(value in (OK, NOT_APPLICABLE) for value in self.status.values())


def _fmt(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def _check_within(spans, duration, name, check):
    if duration is None:
        return
    for span in spans:
        if span["end"] > duration + _END_SLACK_SEC:
            check.errors.append(
                f"{name}: a label ends at {_fmt(span['end'])}, after the recording ends "
                f"({_fmt(duration)}); was it made on a different clip?"
            )
            return


def _coverage(spans: list[dict[str, Any]], within: list[dict[str, Any]]) -> float:
    """Share of the time in ``within`` that ``spans`` also cover (0..1)."""
    total = sum(w["end"] - w["start"] for w in within)
    if total <= 0:
        return 1.0
    covered = 0.0
    for w in within:
        for s in spans:
            covered += max(0.0, min(w["end"], s["end"]) - max(w["start"], s["start"]))
    return min(1.0, covered / total)


def check_clip(folder: Path) -> ClipCheck:
    """Parse and cross-check every label of one clip."""
    check = ClipCheck(clip_id=folder.name)
    # An external corpus (meta.json "dataset") is checked for what it has; its
    # labels are fixed by its publisher, so advice on writing them is moot.
    try:
        external = bool(read_meta(folder).get("dataset"))
    except LabelError:
        external = False
    if external:
        check.status["summary"] = check.status["actions"] = NOT_APPLICABLE

    def run(item: str, fn) -> Any:
        try:
            result = fn()
        except (LabelError, ValueError) as exc:
            check.status[item] = PROBLEM
            check.errors.append(str(exc))
            return None
        return result

    # The recording.
    recording = audio_path(folder.name)
    if not recording.is_file():
        check.status["audio"] = PROBLEM
        check.errors.append(f"recording not found at {recording} (it must have this exact name)")
    else:
        from meeting_assistant.audio.wav_io import probe_wav

        try:
            check.duration = float(probe_wav(recording)["duration_sec"])
            check.status["audio"] = OK
        except Exception as exc:  # noqa: BLE001 -- any unreadable file is one problem
            check.status["audio"] = PROBLEM
            check.errors.append(f"{recording.name} is not a readable WAV file: {exc}")

    # Transcript.
    transcript = run("transcript", lambda: read_text_label(folder / "transcript.txt"))
    if transcript:
        check.status["transcript"] = OK
        if re.search(r"\d", transcript) and not external:
            check.warnings.append(
                "transcript.txt contains digits; write numbers as words, the way they were said"
            )

    # Speaker turns.
    turns = run("turns", lambda: read_turns(folder))
    if turns is not None:
        if not turns:
            check.status["turns"] = PROBLEM
            check.errors.append("turns.txt has no labels")
        else:
            check.status["turns"] = OK
            before = len(check.errors)
            _check_within(turns, check.duration, "turns.txt", check)
            if len(check.errors) > before:
                check.status["turns"] = PROBLEM
            if check.duration and _coverage(turns, [{"start": 0, "end": check.duration}]) < 0.3:
                check.warnings.append(
                    "speaker turns cover less than 30% of the recording; is every turn marked?"
                )

    # Language stretches. An external corpus labels each speaker's segments,
    # so two people talking at once overlap in time.
    spans = None
    if (folder / "languages.txt").is_file():
        spans = run("languages", lambda: read_language_spans(folder / "languages.txt"))
        if spans is not None:
            check.status["languages"] = OK if spans else PROBLEM
            if not spans:
                check.errors.append("languages.txt has no labels")
            before = len(check.errors)
            _check_within(spans, check.duration, "languages.txt", check)
            for previous, current in zip(spans, spans[1:], strict=False):
                if external:
                    break
                if current["start"] < previous["end"] - _OVERLAP_SLACK_SEC:
                    check.errors.append(
                        f"languages.txt: two labels overlap at {_fmt(current['start'])}; "
                        "each moment has exactly one language label"
                    )
                    break
            if len(check.errors) > before:
                check.status["languages"] = PROBLEM
            if turns and spans:
                missing = 1 - _coverage(spans, turns)
                if missing > 0.1:
                    check.warnings.append(
                        f"{missing:.0%} of the speech (by turns.txt) has no language label"
                    )

    # Second annotator (optional).
    if (folder / "languages_b.txt").is_file():
        second = None
        try:
            second = read_language_spans(folder / "languages_b.txt")
        except LabelError as exc:
            check.second_annotator = PROBLEM
            check.errors.append(str(exc))
        if second is not None:
            def key(span):
                return round(span["start"], 2), round(span["end"], 2)

            first_keys = {key(s) for s in spans or []}
            strays = [s for s in second if key(s) not in first_keys]
            if strays:
                check.second_annotator = PROBLEM
                check.errors.append(
                    f"languages_b.txt: the stretch at {_fmt(strays[0]['start'])} does not match "
                    "languages.txt; make the file with `meeting-assistant dataset blind-copy` and "
                    "only change the labels, never the times"
                )
            else:
                check.second_annotator = OK

    # Summary.
    summary = run("summary", lambda: read_text_label(folder / "summary.txt"))
    if summary:
        check.status["summary"] = OK
        if len(summary.split()) < 15:
            check.warnings.append("summary.txt is under 15 words; aim for 3-5 sentences")

    # Action items.
    items = run("actions", lambda: read_action_items(folder))
    if items is not None:
        check.status["actions"] = OK

    # Meta.
    meta = run("meta", lambda: read_meta(folder))
    untouched = not meta or (
        not meta.get("condition") and not meta.get("speakers") and not meta.get("participants")
    )
    if meta is not None and (folder / "meta.json").is_file() and not untouched:
        problems = _meta_problems(meta, turns)
        if problems:
            check.status["meta"] = PROBLEM
            check.errors.extend(f"meta.json: {p}" for p in problems)
        else:
            check.status["meta"] = OK
        participants = meta.get("participants") or []
        if any(not CONSENT_ID.match(str(p)) for p in participants):
            check.warnings.append(
                "meta.json: participants should be consent-form ids such as P01, never names"
            )
    return check


def _meta_problems(meta: dict[str, Any], turns: list[dict[str, Any]] | None) -> list[str]:
    problems = []
    external = bool(meta.get("dataset"))
    if meta.get("condition") not in CONDITIONS:
        problems.append(f"condition must be one of: {', '.join(CONDITIONS)}")
    speakers = meta.get("speakers")
    if not isinstance(speakers, int) or speakers < 1:
        problems.append("speakers must be the number of people who spoke (1 or more)")
    elif turns:
        labelled = len({turn["speaker"] for turn in turns})
        if labelled != speakers:
            problems.append(
                f"speakers says {speakers}, but turns.txt names {labelled} different speakers"
            )
    if external:
        # A published corpus: its own consent and recording records apply, but
        # the terms it is used under must be on file.
        if not str(meta.get("license") or "").strip():
            problems.append("license is empty (the terms this corpus is used under)")
        return problems
    if not str(meta.get("device") or "").strip():
        problems.append("device is empty (the microphone or phone used)")
    try:
        date.fromisoformat(str(meta.get("recorded_on")))
    except ValueError:
        problems.append("recorded_on must be a date like 2026-10-14")
    if not meta.get("participants"):
        problems.append('participants is empty (list the consent-form ids, e.g. ["P01", "P02"])')
    return problems


def check_all(only: str | None = None) -> list[ClipCheck]:
    base = references_dir()
    folders = sorted(d for d in base.glob("*") if d.is_dir()) if base.is_dir() else []
    if only is not None:
        folders = [d for d in folders if d.name == only]
    return [check_clip(folder) for folder in folders]


def format_report(checks: list[ClipCheck]) -> str:
    """The table and problem list printed by ``dataset check``."""
    headers = ["clip", "length", *ITEMS, "2nd"]
    rows = [
        [
            c.clip_id,
            _fmt(c.duration) if c.duration is not None else "?",
            *(c.status[item] for item in ITEMS),
            c.second_annotator,
        ]
        for c in checks
    ]
    widths = [max(len(str(r[i])) for r in [headers, *rows]) for i in range(len(headers))]
    lines = [
        "  ".join(str(v).ljust(w) for v, w in zip(row, widths, strict=True)).rstrip()
        for row in [headers, *rows]
    ]
    lines.append(f"\n{OK} = done   {MISSING} = not done yet   {PROBLEM} = needs fixing (see below)")

    for c in checks:
        if c.errors or c.warnings:
            lines.append(f"\n{c.clip_id}")
            lines.extend(f"  fix:   {e}" for e in c.errors)
            lines.extend(f"  check: {w}" for w in c.warnings)

    complete = sum(c.complete for c in checks)
    with_errors = sum(bool(c.errors) for c in checks)
    lines.append(
        f"\n{complete} of {len(checks)} clip(s) completely labelled; "
        f"{with_errors} with something to fix."
    )
    return "\n".join(lines)
