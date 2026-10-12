"""A run's transcript as a PDF laid out like a professional meeting transcript.

Four versions of the same meeting can be exported:

``original``   what was said, each language in its own script (``tagged``)
``romanized``  the same words in Latin letters (``hinglish``)
``english``    a machine translation into English (see ``language.translate``)
``hindi``      a machine translation into Hindi, in Devanagari

The layout follows the conventions of transcripts produced by transcription
services: a title block with the meeting's details, a list of participants,
a note on how the transcript was made, then the proceedings as speaker turns,
each with the time it began, and page headers and numbered footers.
Consecutive segments by one speaker form one turn, since diarization often
splits a single turn at pauses.

Fonts are bundled (Noto Sans and Noto Sans Devanagari, SIL Open Font License,
``fonts/OFL.txt``) and text is shaped with HarfBuzz, without which Devanagari
conjuncts and vowel signs come out in the wrong order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fpdf import FPDF

from meeting_assistant.errors import ArtifactError
from meeting_assistant.io_utils import read_json
from meeting_assistant.language.translate import ORIGINAL_CHAIN, load_translation
from meeting_assistant.paths import RunPaths

Version = Literal["original", "romanized", "english", "hindi"]
VERSIONS: tuple[Version, ...] = ("original", "romanized", "english", "hindi")

VERSION_LABEL: dict[str, str] = {
    "original": "Original, as spoken",
    "romanized": "Romanized (Hinglish)",
    "english": "English translation",
    "hindi": "Hindi translation",
}

FONTS = Path(__file__).parent / "fonts"
# Consecutive segments by the same speaker join into one turn unless a pause
# this long separates them.
TURN_GAP_SEC = 5.0

INK = (33, 37, 41)
MUTED = (108, 117, 125)
RULE = (206, 212, 218)
ACCENT = (31, 78, 121)
SHADE = (244, 246, 248)


class TranslationMissing(LookupError):
    """The requested translation has not been made for the current transcript."""


@dataclass
class TranscriptVersion:
    version: Version
    segments: list[dict[str, Any]]
    translation: dict[str, Any] | None = None


def load_version(paths: RunPaths, version: Version) -> TranscriptVersion:
    """The segments of one version of the transcript.

    Raises:
        ArtifactError: the run has no transcript of that kind.
        TranslationMissing: a translation was asked for but not made yet.
    """
    if version == "original":
        for name in ORIGINAL_CHAIN:
            if paths.has(name):
                return TranscriptVersion(version, read_json(paths.artifact(name)))
        raise ArtifactError(f"Run {paths.run_id} has no transcript yet")
    if version == "romanized":
        if not paths.has("hinglish"):
            raise ArtifactError(f"Run {paths.run_id} has no romanized transcript")
        return TranscriptVersion(version, read_json(paths.artifact("hinglish")))
    document = load_translation(paths, version)
    if document is None:
        raise TranslationMissing(f"This meeting has not been translated into {version.title()} yet")
    return TranscriptVersion(version, document["segments"], document)


# ---------------------------------------------------------------------------
# Content helpers
# ---------------------------------------------------------------------------
def timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _is_unknown(label: str) -> bool:
    return not label or label.upper().startswith("UNKNOWN")


def speaker_names(segments: list[dict[str, Any]]) -> dict[str, str]:
    """Automatic labels to "Speaker 1", "Speaker 2"… in order of first speaking."""
    names: dict[str, str] = {}
    for segment in segments:
        label = str(segment.get("speaker") or "")
        if label in names:
            continue
        names[label] = (
            "Unidentified speaker"
            if _is_unknown(label)
            else f"Speaker {sum(not _is_unknown(k) for k in names) + 1}"
        )
    return names


@dataclass
class Turn:
    speaker: str
    start: float
    texts: list[str]
    untranslated: bool = False


def turns(segments: list[dict[str, Any]]) -> list[Turn]:
    out: list[Turn] = []
    last_end = None
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        speaker = str(segment.get("speaker") or "")
        start = float(segment.get("start") or 0.0)
        failed = segment.get("translation") == "failed"
        if (
            out
            and out[-1].speaker == speaker
            and last_end is not None
            and start - last_end <= TURN_GAP_SEC
            and not failed
            and not out[-1].untranslated
        ):
            out[-1].texts.append(text)
        else:
            out.append(Turn(speaker, start, [text], untranslated=failed))
        last_end = float(segment.get("end") or start)
    return out


def _languages(segments: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for segment in segments:
        language = segment.get("language")
        if language:
            counts[language] = counts.get(language, 0) + 1
    if not counts:
        return "Not detected"
    named = {"Code-Mixed": "Hindi–English mixed"}
    return ", ".join(named.get(k, k) for k, _ in sorted(counts.items(), key=lambda kv: -kv[1]))


def _date(value: str | None) -> str:
    if not value:
        return "Unknown"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return f"{parsed.day} {parsed:%B %Y}, {parsed:%H:%M}"


def _duration(segments: list[dict[str, Any]], metadata: dict[str, Any] | None) -> str:
    if metadata and metadata.get("duration_sec") is not None:
        return timestamp(float(metadata["duration_sec"]))
    if not segments:
        return "00:00:00"
    return timestamp(max(float(s.get("end") or 0) for s in segments))


def meeting_name(manifest: dict[str, Any], run_id: str) -> str:
    source = (manifest.get("provenance") or {}).get("input") or {}
    name = source.get("name") or Path(str(source.get("path") or "")).name
    if name:
        return Path(name).stem
    return "Live session" if manifest.get("mode") == "live" else run_id


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
class _TranscriptPDF(FPDF):
    def __init__(self, *, title: str, version_label: str, footer_note: str) -> None:
        super().__init__(format="A4")
        self.title_text = title
        self.version_label = version_label
        self.footer_note = footer_note
        self.set_margins(20, 20, 20)
        self.set_auto_page_break(True, margin=20)
        for family, regular, bold in (
            ("Sans", "NotoSans-Regular.ttf", "NotoSans-Bold.ttf"),
            ("Deva", "NotoSansDevanagari-Regular.ttf", "NotoSansDevanagari-Bold.ttf"),
        ):
            self.add_font(family, "", str(FONTS / regular))
            self.add_font(family, "B", str(FONTS / bold))
        self.set_fallback_fonts(["Deva"], exact_match=False)
        self.set_text_shaping(True)
        self.set_title(f"{title} — transcript ({version_label})")
        self.set_creator("Meeting Assistant")

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font("Sans", "", 8)
        self.set_text_color(*MUTED)
        self.cell(self.epw / 2, 5, self.title_text)
        self.cell(self.epw / 2, 5, f"Transcript · {self.version_label}", align="R")
        self.ln(6)
        self.set_draw_color(*RULE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(5)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("Sans", "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(self.epw * 0.75, 5, self.footer_note)
        self.cell(self.epw * 0.25, 5, f"Page {self.page_no()} of {{nb}}", align="R")

    # -- blocks ---------------------------------------------------------------
    def details(self, rows: list[tuple[str, str]]) -> None:
        label_w = 46
        for label, value in rows:
            self.set_font("Sans", "B", 9)
            self.set_text_color(*MUTED)
            y = self.get_y()
            self.cell(label_w, 6, label.upper())
            self.set_xy(self.l_margin + label_w, y)
            self.set_font("Sans", "", 10)
            self.set_text_color(*INK)
            self.multi_cell(self.epw - label_w, 6, value, new_x="LMARGIN", new_y="NEXT")

    def section(self, title: str) -> None:
        # A heading never ends a page: keep room for the first lines under it.
        if self.get_y() + 40 > self.page_break_trigger:
            self.add_page()
        self.ln(4)
        self.set_font("Sans", "B", 10)
        self.set_text_color(*ACCENT)
        self.cell(0, 7, title.upper(), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*ACCENT)
        self.set_line_width(0.4)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_line_width(0.2)
        self.ln(3)

    def subheading(self, text: str) -> None:
        self.ln(1)
        self.set_font("Sans", "B", 9.5)
        self.set_text_color(*INK)
        self.cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")

    def paragraph(self, text: str, *, size: float = 10, color=INK) -> None:
        self.set_font("Sans", "", size)
        self.set_text_color(*color)
        self.multi_cell(0, size * 0.55, text, align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def bullets(self, items: list[str]) -> None:
        self.set_font("Sans", "", 10)
        self.set_text_color(*INK)
        for item in items:
            y = self.get_y()
            self.set_xy(self.l_margin + 2, y)
            self.cell(5, 5.5, "•")
            self.set_xy(self.l_margin + 7, y)
            self.multi_cell(self.epw - 7, 5.5, item, align="L", new_x="LMARGIN", new_y="NEXT")
            self.ln(0.8)

    def table_rows(
        self,
        headings: tuple[str, ...],
        rows: list[tuple[str, ...]],
        widths: tuple[float, ...],
        align: tuple[str, ...],
    ) -> None:
        """A table whose cells wrap; the heading row repeats on a new page."""
        from fpdf.fonts import FontFace

        self.set_font("Sans", "", 9)
        self.set_text_color(*INK)
        self.set_draw_color(*RULE)
        with self.table(
            width=self.epw,
            col_widths=widths,
            text_align=align,
            line_height=5,
            padding=(1.6, 1.5),
            borders_layout="HORIZONTAL_LINES",
            headings_style=FontFace(emphasis="BOLD", color=MUTED, fill_color=SHADE, size_pt=8.5),
            repeat_headings=1,
        ) as table:
            table.row(headings)
            for row in rows:
                table.row(row)
        self.ln(2)

    def bars(self, rows: list[tuple[str, float, str]]) -> None:
        """Labelled horizontal bars: (label, fraction 0..1, value text)."""
        label_w, value_w = 52, 26
        bar_w = self.epw - label_w - value_w - 4
        for label, fraction, value in rows:
            y = self.get_y()
            self.set_font("Sans", "", 9)
            self.set_text_color(*INK)
            self.cell(label_w, 6, label)
            self.set_fill_color(*SHADE)
            self.rect(self.l_margin + label_w, y + 1.6, bar_w, 2.8, style="F")
            self.set_fill_color(*ACCENT)
            if fraction > 0:
                self.rect(self.l_margin + label_w, y + 1.6, max(0.6, bar_w * fraction), 2.8, "F")
            self.set_xy(self.l_margin + label_w + bar_w + 4, y)
            self.set_text_color(*MUTED)
            self.cell(value_w, 6, value, align="R", new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def note(self, text: str) -> None:
        self.ln(3)
        self.set_fill_color(*SHADE)
        self.set_font("Sans", "", 8.5)
        self.set_text_color(*MUTED)
        self.multi_cell(
            0, 4.8, text, fill=True, padding=3, align="L", new_x="LMARGIN", new_y="NEXT"
        )

    def turn(self, time_text: str, speaker: str, text: str, *, flag: str | None = None) -> None:
        time_w, speaker_w = 20, 34
        text_x = self.l_margin + time_w + speaker_w
        # Keep a turn's first lines with its label instead of orphaning the label.
        if self.get_y() + 12 > self.page_break_trigger:
            self.add_page()
        y = self.get_y()
        self.set_font("Sans", "", 8.5)
        self.set_text_color(*MUTED)
        self.set_xy(self.l_margin, y + 0.4)
        self.cell(time_w, 5.6, f"[{time_text}]")
        self.set_font("Sans", "B", 9.5)
        self.set_text_color(*ACCENT)
        self.set_xy(self.l_margin + time_w, y)
        self.multi_cell(speaker_w - 2, 6, f"{speaker}:", new_x="RIGHT", new_y="TOP")
        label_bottom = self.get_y()
        self.set_xy(text_x, y)
        self.set_font("Sans", "", 10)
        self.set_text_color(*INK)
        self.multi_cell(
            self.w - self.r_margin - text_x, 6, text, align="L", new_x="LMARGIN", new_y="NEXT"
        )
        if flag:
            self.set_x(text_x)
            self.set_font("Sans", "", 8)
            self.set_text_color(*MUTED)
            self.multi_cell(
                self.w - self.r_margin - text_x, 4.5, flag, new_x="LMARGIN", new_y="NEXT"
            )
        self.set_y(max(self.get_y(), label_bottom) + 2.5)


def _stage_error(manifest: dict[str, Any], name: str) -> str | None:
    """Why a stage produced nothing, as recorded in the manifest."""
    for stage in reversed(manifest.get("stages") or []):
        if stage.get("name") == name:
            if stage.get("error"):
                return str(stage["error"])
            return None if stage.get("status") == "ok" else stage.get("status")
    return None


def _stage_counts(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    for stage in reversed(manifest.get("stages") or []):
        if stage.get("name") == name:
            return stage.get("counts") or {}
    return {}


def _speaking_time(segments: list[dict[str, Any]], key: str) -> dict[str, float]:
    """Seconds of speech per value of ``key``, in order of first appearance."""
    out: dict[str, float] = {}
    for segment in segments:
        value = str(segment.get(key) or "")
        seconds = max(0.0, float(segment.get("end") or 0) - float(segment.get("start") or 0))
        out[value] = out.get(value, 0.0) + seconds
    return out


def _minutes_seconds(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}" if total < 3600 else timestamp(total)


def _share(part: float, whole: float) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "—"


def render_transcript_pdf(paths: RunPaths, version: Version) -> tuple[bytes, str]:
    """Render one version of a run's transcript, with the meeting's summary,
    action items and statistics; returns ``(pdf_bytes, file_name)``.

    The summary, action items and statistics are the same in every version:
    the pipeline produced them once, from the meeting.

    Raises:
        ArtifactError: the run has no transcript of that kind.
        TranslationMissing: a translation was asked for but not made yet.
    """
    manifest = read_json(paths.manifest_path) if paths.manifest_path.exists() else {}
    provenance = manifest.get("provenance") or {}
    settings = provenance.get("settings") or {}

    def artifact(name: str) -> Any:
        return read_json(paths.artifact(name)) if paths.has(name) else None

    metadata = artifact("metadata")
    summary = artifact("summary")
    actions = artifact("action_items")
    stats = artifact("speaker_stats")
    chosen = load_version(paths, version)
    # Who spoke and in which language comes from the original, whatever version is shown.
    spoken = load_version(paths, "original").segments if version != "original" else chosen.segments

    name = meeting_name(manifest, paths.run_id)
    label = VERSION_LABEL[version]
    generated = datetime.now()
    llm = settings.get("ollama_model") or "the language model"
    pdf = _TranscriptPDF(
        title=name,
        version_label=label,
        footer_note=(
            f"Generated {generated:%d %b %Y %H:%M} by Meeting Assistant · run {paths.run_id}"
        ),
    )
    pdf.add_page()

    # -- title block ----------------------------------------------------------------
    pdf.set_font("Sans", "B", 9)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 5, "MEETING TRANSCRIPT", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Sans", "B", 20)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 10, name, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Sans", "", 11)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 7, label, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    names = speaker_names(spoken)
    speakers = [key for key in names if not _is_unknown(key)]
    recording = (provenance.get("input") or {}).get("name")
    live = manifest.get("mode") == "live"
    totals = (stats or {}).get("totals") or {}
    details = [
        ("Date", _date(provenance.get("captured_at"))),
        ("Duration", _duration(spoken, metadata)),
        ("Recording", recording or ("Live microphone session" if live else "—")),
        ("Participants", f"{len(speakers)} ({', '.join(names[k] for k in speakers)})"),
        ("Languages spoken", _languages(spoken)),
    ]
    if totals.get("word_count"):
        turns_count = totals.get("utterance_count", 0)
        details.append(("Words spoken", f"{totals['word_count']} in {turns_count} turns"))
    details += [("This transcript", label), ("Reference", paths.run_id)]
    pdf.details(details)

    if chosen.translation is not None:
        doc = chosen.translation
        target = version.title()
        notice = (
            f"Machine translation into {target} by {doc.get('model')}, made "
            f"{_date(doc.get('created_at'))}. Passages already spoken in {target} are reproduced "
            "as spoken. The original-language transcript is the authoritative record."
        )
        if doc.get("segments_failed"):
            notice += " Passages the model could not translate are shown as spoken, and marked."
        pdf.note(notice)

    # -- summary ----------------------------------------------------------------------
    pdf.section("Summary")
    if summary and str(summary.get("summary") or "").strip():
        pdf.paragraph(str(summary["summary"]).strip())
        if summary.get("highlights"):
            pdf.subheading("Points discussed")
            pdf.bullets([str(h) for h in summary["highlights"]])
        pdf.subheading("Decisions")
        if summary.get("key_decisions"):
            pdf.bullets([str(d) for d in summary["key_decisions"]])
        else:
            pdf.paragraph("No decisions were recorded.", size=9.5, color=MUTED)
        pdf.paragraph(
            f"Written automatically in English by {llm} from the transcript; check important "
            "points against the transcript.",
            size=8,
            color=MUTED,
        )
    else:
        reason = _stage_error(manifest, "summary")
        pdf.paragraph(
            "No summary was produced" + (f" ({reason})." if reason else "."),
            size=9.5,
            color=MUTED,
        )

    # -- action items -----------------------------------------------------------------
    pdf.section("Action items")
    items = (actions or {}).get("action_items") or []
    if items:

        def owner(value: Any) -> str:
            text = str(value or "").strip()
            return names.get(text, text) or "—"

        pdf.table_rows(
            ("#", "Owner", "Task", "Deadline", "Status"),
            [
                (
                    str(i),
                    owner(item.get("person")),
                    str(item.get("task") or ""),
                    str(item.get("deadline") or "—"),
                    str(item.get("status") or "—"),
                )
                for i, item in enumerate(items, start=1)
            ],
            widths=(6, 26, 74, 30, 20),
            align=("RIGHT", "LEFT", "LEFT", "LEFT", "LEFT"),
        )
        pdf.paragraph(
            f"Extracted automatically by {llm}. Owners and deadlines appear only where they "
            "were said in the meeting.",
            size=8,
            color=MUTED,
        )
    elif actions is not None:
        pdf.paragraph("No action items were identified.", size=9.5, color=MUTED)
    else:
        reason = _stage_error(manifest, "action_items")
        pdf.paragraph(
            "Action items were not extracted" + (f" ({reason})." if reason else "."),
            size=9.5,
            color=MUTED,
        )

    # -- participation ----------------------------------------------------------------
    pdf.section("Participation")
    per_speaker = (stats or {}).get("speakers") or {}
    time_by = _speaking_time(spoken, "speaker")
    total_time = sum(time_by.values())
    rows = []
    for key in names:  # in the order they first spoke, so Speaker 10 follows Speaker 9
        stat = per_speaker.get(key) or {}
        seconds = float(stat.get("speaking_time_sec", time_by.get(key, 0.0)))
        wpm = stat.get("words_per_minute")
        rows.append(
            (
                names[key],
                key or "—",
                _minutes_seconds(seconds),
                _share(time_by.get(key, 0.0), total_time),
                str(stat.get("utterance_count", "—")),
                str(stat.get("word_count", "—")),
                f"{float(wpm):.0f}" if wpm else "—",
            )
        )
    pdf.table_rows(
        ("Speaker", "Automatic label", "Speaking time", "Share", "Turns", "Words", "Words/min"),
        rows,
        widths=(28, 32, 24, 16, 16, 16, 20),
        align=("LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"),
    )
    if total_time:
        pdf.bars(
            [
                (
                    names[key],
                    time_by.get(key, 0.0) / total_time,
                    _share(time_by.get(key, 0.0), total_time),
                )
                for key in names
            ]
        )
    if totals.get("unattributed_time_sec"):
        pdf.paragraph(
            f"{_minutes_seconds(totals['unattributed_time_sec'])} of speech "
            f"({totals.get('unattributed_pct', 0):.0f}%) could not be attributed to a speaker.",
            size=8.5,
            color=MUTED,
        )

    by_language = {k: v for k, v in _speaking_time(spoken, "language").items() if k}
    language_total = sum(by_language.values())
    if language_total:
        pdf.subheading("Languages, by speaking time")
        named = {"Code-Mixed": "Hindi–English mixed"}
        pdf.bars(
            [
                (named.get(k, k), v / language_total, _share(v, language_total))
                for k, v in sorted(by_language.items(), key=lambda kv: -kv[1])
            ]
        )

    # -- transcript -------------------------------------------------------------------
    pdf.add_page()
    pdf.section("Transcript")
    pdf.paragraph(
        "Speakers are numbered in the order they first spoke; names are not identified "
        "automatically. Timestamps [hh:mm:ss] are measured from the start of the recording.",
        size=8,
        color=MUTED,
    )
    for item in turns(chosen.segments):
        pdf.turn(
            timestamp(item.start),
            names.get(item.speaker, item.speaker or "Unidentified speaker"),
            " ".join(item.texts),
            flag="[Not translated: shown as spoken]" if item.untranslated else None,
        )
    pdf.ln(4)
    pdf.set_font("Sans", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 6, "[End of transcript]", align="C", new_x="LMARGIN", new_y="NEXT")

    # -- how it was made ----------------------------------------------------------------
    pdf.section("About this transcript")
    pdf.paragraph(
        "This record was produced automatically from the recording. Words are transcribed as "
        "they were recognized and may contain errors; check important passages against the "
        "recording.",
        size=9,
        color=MUTED,
    )
    git = provenance.get("git") or {}
    code = str(git.get("commit") or "")[:10] or "unknown"
    if git.get("dirty"):
        code += " (with uncommitted changes)"
    device = ", ".join(
        str(v) for v in (settings.get("whisper_device"), settings.get("whisper_compute_type")) if v
    )
    whisper = f"Whisper {settings.get('whisper_model_size', '')}".strip()
    about = [
        ("Speech recognition", whisper + (f" ({device})" if device else "")),
        ("Speaker separation", str(settings.get("diarization_model") or "—")),
    ]
    if paths.has("hinglish"):
        prompt = _stage_counts(manifest, "hinglish").get("prompt_version")
        about.append(("Romanization", llm + (f" ({prompt})" if prompt else "")))
    if summary is not None or actions is not None:
        prompts = [
            str(_stage_counts(manifest, n).get("prompt_version") or "")
            for n in ("summary", "action_items")
        ]
        prompts = [v for v in prompts if v]
        about.append(("Summary and actions", llm + (f" ({', '.join(prompts)})" if prompts else "")))
    if chosen.translation is not None:
        doc = chosen.translation
        about.append(("Translation", f"{doc.get('model')} ({doc.get('prompt_version')})"))
    about += [
        ("Code version", code),
        ("Configuration", str(provenance.get("config_hash") or "—")),
        ("Processed", _date(provenance.get("finished_at") or provenance.get("captured_at"))),
        ("Run reference", paths.run_id),
    ]
    pdf.details(about)

    file_name = f"{name}_transcript_{version}.pdf"
    return bytes(pdf.output()), file_name
