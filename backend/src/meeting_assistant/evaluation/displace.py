"""Import the DISPLACE 2023 development set as an external evaluation benchmark.

Behind ``meeting-assistant dataset import-displace <corpus_dir>``. DISPLACE
(DIarization of SPeaker and LAnguage in Conversational Environments; Baghel et
al., Interspeech 2023) is a set of natural, far-field, multi-speaker
conversations recorded in India, labelled for who spoke when, which language
and what was said. Its Hindi-English sessions test this project's diarization,
language identification and ASR on real conversations it was never tuned on,
and against published baselines -- the one thing a self-recorded dataset cannot
give. It has no summaries or action items, so the meeting-intelligence stages
are not scored on it.

The release ships one ``jsons/<session>.json`` per ``wav/<session>.wav``: a list
of segments ``{"startTime", "endTime", "speaker", "language", "content"}``,
language-homogeneous (often a few words long), with Hindi in Devanagari and
English in Latin script -- the same form Whisper emits. Each Hindi-English
session becomes an ordinary reference clip, ``displace-<session>``, that
``meeting-assistant dataset check`` and ``eval`` read like any other:

=====================  ========================================================
``transcript.txt``     The cleaned ``content`` of every segment, in start order.
``turns.rttm``         One turn per speech segment, speaker ``S1``, ``S2``, ...
``languages.txt``      One ``start<TAB>end<TAB>Hindi|English`` line per segment.
                       Segments of different speakers may overlap in time.
``meta.json``          ``dataset``, the session, speaker count, licence terms
                       and what the import left out, and why.
=====================  ========================================================

Policy, applied identically to every session and stated so the paper can cite
it:

* **Session selection.** A session is kept only if both Hindi and English are
  spoken in it and speech labelled with any other language (or with no usable
  language) is at most :data:`MAX_OTHER_SHARE` of its labelled speech. That
  drops the Kannada-English and Malayalam-English sessions while keeping a
  Hindi-English session with one stray mislabelled segment.
* **Transcript.** Annotation tags (``[sil]``, ``[laugh]``, ``[unkwn]`` and the
  rest of :data:`TAGS`) are removed: they are not words, and unintelligible
  speech (``[unkwn]``) has no reference words to compare with. Fillers
  (``hmm``, ``ahh``) are kept, because they were spoken; ``eval`` already
  reports a filler-stripped WER beside the plain one.
* **Speech.** A segment whose content is nothing but silence or non-speech
  tags (:data:`NON_SPEECH_TAGS`) is not a speaker turn. Every other segment is,
  including laughter and unintelligible speech, since a speaker is audibly
  talking.
* **Recording length.** A few sessions' labels run a second or more past the
  end of their audio; labels are cut at the end of the recording (one wholly
  after it is dropped) and the count is recorded.
* **Language.** ``hi``/``en`` labels (any case) become Hindi/English; segments
  labelled otherwise stay in the transcript and the speaker turns but get no
  language label, and how much was left out is recorded in ``meta.json``.

The audio is hard-linked into ``data/audio`` when the corpus is on the same
drive (copied otherwise). Neither the audio nor the labels are ever committed:
the DISPLACE terms allow research use with citation and forbid redistribution.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from meeting_assistant.errors import ArtifactError
from meeting_assistant.evaluation.references import read_meta
from meeting_assistant.evaluation.rttm import write_rttm
from meeting_assistant.io_utils import write_json, write_text
from meeting_assistant.language.detection import ENGLISH, HINDI

DATASET = "displace2023-dev"
CLIP_PREFIX = "displace-"
CITATION = (
    "S. Baghel et al., 'The DISPLACE Challenge 2023 - DIarization of SPeaker and LAnguage "
    "in Conversational Environments', Proc. Interspeech 2023"
)
LICENSE = (
    "DISPLACE challenge terms and conditions: research use with citation; "
    "the audio and annotations must not be redistributed."
)

# Speech in a language other than Hindi or English, as a share of a session's
# labelled speech, above which the session is not a Hindi-English one.
MAX_OTHER_SHARE = 0.01

_LANGUAGES = {"hi": HINDI, "en": ENGLISH}
# Every annotation tag found in the release, with misspellings.
TAGS = ("sil", "unkwn", "unknow", "laugh", "lipsmack", "other", "breath", "cough", "img")
NON_SPEECH_TAGS = ("sil", "img")
_TAG_RE = re.compile(r"[\[<]\s*(" + "|".join(TAGS) + r")\s*[\]>]", re.IGNORECASE)
_NON_SPEECH_RE = re.compile(r"[\[<]\s*(" + "|".join(NON_SPEECH_TAGS) + r")\s*[\]>]", re.IGNORECASE)
_SPEAKER_RE = re.compile(r"_(S\d+)_")


@dataclass
class Session:
    """One DISPLACE conversation as released."""

    session_id: str
    segments: list[dict[str, Any]]
    wav: Path

    @property
    def clip_id(self) -> str:
        return f"{CLIP_PREFIX}{self.session_id.lower()}"


@dataclass
class ImportResult:
    session_id: str
    clip_id: str
    kept: bool
    reason: str = ""
    duration_sec: float = 0.0
    speakers: int = 0
    languages: dict[str, float] = field(default_factory=dict)
    audio: str = ""


def clean_content(text: str) -> str:
    """A segment's words: tags removed, stray brackets dropped, spaces collapsed."""
    text = _TAG_RE.sub(" ", text or "")
    text = re.sub(r"[\[\]<>]", " ", text)
    return " ".join(text.split())


def is_speech(segment: dict[str, Any]) -> bool:
    """False for a segment that is only silence or non-speech tags."""
    remainder = _NON_SPEECH_RE.sub(" ", segment.get("content") or "")
    return bool(remainder.strip())


def speaker_label(raw: str) -> str:
    """``20221117_1445_B020_S1_BaEn`` -> ``S1`` (the raw id if it has no ``S<n>``)."""
    match = _SPEAKER_RE.search(f"{raw}_")
    return match.group(1) if match else raw


def language_of(segment: dict[str, Any]) -> str | None:
    return _LANGUAGES.get(str(segment.get("language") or "").strip().lower())


def read_session(json_path: Path, wav_dir: Path) -> Session:
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError(
            f"{json_path.name}: not a readable DISPLACE annotation ({exc})"
        ) from exc
    if not isinstance(data, dict) or len(data) != 1:
        raise ArtifactError(f"{json_path.name}: expected one session key, found {list(data)[:3]}")
    session_id, raw = next(iter(data.items()))
    segments = [
        {
            "start": float(s["startTime"]),
            "end": float(s["endTime"]),
            "speaker": str(s["speaker"]),
            "language": s.get("language"),
            "content": s.get("content") or "",
        }
        for s in raw
        if float(s["endTime"]) > float(s["startTime"])
    ]
    segments.sort(key=lambda s: (s["start"], s["end"]))
    return Session(session_id=str(session_id), segments=segments, wav=wav_dir / f"{session_id}.wav")


def language_time(segments: list[dict[str, Any]]) -> Counter:
    """Seconds of speech per language label: Hindi, English, or ``other``."""
    seconds: Counter = Counter()
    for segment in segments:
        if is_speech(segment):
            seconds[language_of(segment) or "other"] += segment["end"] - segment["start"]
    return seconds


def selection_reason(segments: list[dict[str, Any]]) -> str | None:
    """Why a session is not a Hindi-English one, or ``None`` if it is."""
    seconds = language_time(segments)
    total = sum(seconds.values())
    if not total:
        return "no labelled speech"
    if not seconds[HINDI] or not seconds[ENGLISH]:
        return "not both Hindi and English"
    other = seconds["other"] / total
    if other > MAX_OTHER_SHARE:
        return f"{other:.0%} of the speech is in another language"
    return None


def find_sessions(corpus_dir: Path) -> list[Path]:
    """The release's annotation files, wherever the zip put its top folder."""
    corpus_dir = Path(corpus_dir)
    for base in (corpus_dir, *sorted(p for p in corpus_dir.iterdir() if p.is_dir())):
        found = sorted((base / "jsons").glob("*.json")) or sorted((base / "json").glob("*.json"))
        if found:
            return found
    raise ArtifactError(f"No DISPLACE annotations (jsons/*.json) under {corpus_dir}")


def _place_audio(source: Path, target: Path) -> str:
    """Hard-link ``source`` to ``target`` (copy across drives); reuse an identical file."""
    if target.exists():
        if target.stat().st_size == source.stat().st_size:
            return "kept"
        raise ArtifactError(
            f"{target} already exists and differs from {source}; move it away to re-import"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
        return "linked"
    except OSError:
        shutil.copy2(source, target)
        return "copied"


def _clip_to(segments: list[dict[str, Any]], duration: float | None) -> list[dict[str, Any]]:
    """Segments cut at ``duration`` (the recording's end); later ones dropped."""
    if duration is None:
        return segments
    return [{**s, "end": min(s["end"], duration)} for s in segments if s["start"] < duration]


def recording_duration(wav: Path) -> float | None:
    from meeting_assistant.audio.wav_io import probe_wav

    try:
        return float(probe_wav(wav)["duration_sec"])
    except Exception:  # noqa: BLE001 -- an unreadable file is reported by `dataset check`
        return None


def write_clip(session: Session, references_dir: Path, duration: float | None = None) -> Path:
    """Write one session's labels as a reference clip folder; returns the folder.

    Refuses to overwrite a folder that was not made by this importer, so a
    hand-labelled clip can never be replaced by accident.
    """
    folder = references_dir / session.clip_id
    if folder.exists() and read_meta(folder).get("dataset") != DATASET:
        raise ArtifactError(f"{folder} exists and was not imported from DISPLACE; not touching it")

    within = _clip_to(session.segments, duration)
    speech = [s for s in within if is_speech(s)]
    turns = [{"start": s["start"], "end": s["end"], "speaker": speaker_label(s["speaker"])}
             for s in speech]
    labelled = [s for s in speech if language_of(s)]
    words = [clean_content(s["content"]) for s in speech]

    header = (
        f"# DISPLACE 2023 dev set, session {session.session_id}: generated by "
        "`meeting-assistant dataset import-displace`. Do not edit; re-import instead.\n"
    )
    write_text(folder / "transcript.txt", header + "\n".join(w for w in words if w) + "\n")
    write_rttm(folder / "turns.rttm", turns, file_id=session.clip_id)
    write_text(
        folder / "languages.txt",
        header + "".join(
            f"{s['start']:.3f}\t{s['end']:.3f}\t{language_of(s)}\n" for s in labelled
        ),
    )
    seconds = language_time(session.segments)
    write_json(
        folder / "meta.json",
        {
            "dataset": DATASET,
            "session": session.session_id,
            "condition": "code-mixed",
            "speakers": len({t["speaker"] for t in turns}),
            "recording": "far-field, single channel, 16 kHz (natural conversation)",
            "license": LICENSE,
            "citation": CITATION,
            "language_seconds": {k: round(v, 1) for k, v in sorted(seconds.items())},
            "excluded": {
                "after_recording_end": sum(
                    s["end"] > duration for s in session.segments
                ) if duration is not None else 0,
                "non_speech_segments": len(within) - len(speech),
                "segments_without_language": len(speech) - len(labelled),
            },
        },
    )
    return folder


def import_corpus(
    corpus_dir: Path, references_dir: Path, audio_dir: Path, *, only: set[str] | None = None
) -> list[ImportResult]:
    """Import every Hindi-English session; report every session either way."""
    json_paths = find_sessions(Path(corpus_dir))
    wav_dir = json_paths[0].parent.parent / "wav"
    results = []
    for json_path in json_paths:
        session = read_session(json_path, wav_dir)
        if only and session.session_id not in only:
            continue
        seconds = language_time(session.segments)
        result = ImportResult(
            session_id=session.session_id,
            clip_id=session.clip_id,
            kept=False,
            duration_sec=max((s["end"] for s in session.segments), default=0.0),
            speakers=len({speaker_label(s["speaker"]) for s in session.segments if is_speech(s)}),
            languages={k: round(v / 60, 1) for k, v in seconds.most_common()},
        )
        reason = selection_reason(session.segments)
        if reason is None and not session.wav.is_file():
            reason = f"audio missing ({session.wav.name})"
        if reason is not None:
            result.reason = reason
        else:
            write_clip(session, references_dir, recording_duration(session.wav))
            result.audio = _place_audio(session.wav, audio_dir / f"{session.clip_id}.wav")
            result.kept = True
        results.append(result)
    return results
