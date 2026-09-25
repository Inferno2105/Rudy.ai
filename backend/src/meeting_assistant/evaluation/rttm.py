"""RTTM read/write, and conversion from an Audacity label-track export.

RTTM (Rich Transcription Time Marked) is the standard file format diarization
tooling exchanges turns in — one line per turn, whitespace-separated. This
project never hand-writes one: turn boundaries are labelled by ear in
Audacity, which exports a much simpler tab-separated ``start\\tend\\tlabel``
format, and :func:`labels_to_rttm` is the whole reason that manual labelling
step is only "mark boundaries and type a speaker name" rather than "type RTTM
syntax by hand" — the conversion turns roughly 20-30 minutes of mouse work per
clip into a scoreable reference, rather than needing that same labelling done
twice.

Every function here works on plain ``{"start", "end", "speaker"}`` segment
dicts — the diarizer's own output shape — so a reference loaded from an RTTM
file and a hypothesis loaded straight from a run's own
``02_diarization.json`` are already the same shape and need no adapting
before :mod:`meeting_assistant.evaluation.der` compares them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from meeting_assistant.io_utils import write_text

_RTTM_TYPE = "SPEAKER"


def segments_to_rttm_lines(segments: list[dict[str, Any]], file_id: str) -> list[str]:
    """One RTTM ``SPEAKER`` line per segment.

    Channel is always ``1`` (this project only ever records mono); the two
    confidence/``<NA>`` fields RTTM reserves are left as ``<NA>`` since nothing
    here produces them.
    """
    lines = []
    for segment in segments:
        start = segment["start"]
        duration = segment["end"] - segment["start"]
        speaker = segment["speaker"]
        lines.append(
            f"{_RTTM_TYPE} {file_id} 1 {start:.3f} {duration:.3f} <NA> <NA> {speaker} <NA> <NA>"
        )
    return lines


def write_rttm(path: str | Path, segments: list[dict[str, Any]], file_id: str) -> Path:
    """Write ``segments`` to ``path`` in RTTM format."""
    lines = segments_to_rttm_lines(segments, file_id)
    return write_text(path, "\n".join(lines) + ("\n" if lines else ""))


def read_rttm(path: str | Path) -> list[dict[str, Any]]:
    """Read an RTTM file back into ``{"start", "end", "speaker"}`` segments.

    Non-``SPEAKER`` line types (RTTM also defines ``NOISE``, ``LEXEME``, and
    others this project never emits) and blank lines are skipped rather than
    raising, so a hand-edited or third-party RTTM file with a stray comment
    line does not break loading.
    """
    segments = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or not line.startswith(_RTTM_TYPE):
            continue
        parts = line.split()
        start = float(parts[3])
        duration = float(parts[4])
        speaker = parts[7]
        segments.append(
            {"start": round(start, 3), "end": round(start + duration, 3), "speaker": speaker}
        )
    return segments


def labels_to_rttm(label_path: str | Path) -> list[dict[str, Any]]:
    """Convert an Audacity label-track export into RTTM-shaped segments.

    Audacity's export format is one turn per line: ``start\\tend\\tlabel``,
    tab-separated, no header. ``label`` is used directly as the speaker name,
    so labelling convention (``A``/``B``, ``SPEAKER_1``, a real name) is the
    annotator's choice — this function does not normalize or validate it.

    Raises:
        ValueError: a non-blank line does not have the three expected fields.
    """
    segments = []
    text = Path(label_path).read_text(encoding="utf-8")
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            raise ValueError(
                f"{label_path}:{line_number}: expected 'start\\tend\\tlabel', got {line!r}"
            )
        start, end, label = float(parts[0]), float(parts[1]), parts[2].strip()
        segments.append({"start": round(start, 3), "end": round(end, 3), "speaker": label})
    return segments
