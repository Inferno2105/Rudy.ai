"""Full translations of a transcript into English or into Hindi, for reading.

The pipeline keeps what was said in the script it was said in (``tagged``) and
a romanized copy (``hinglish``); neither changes the words. A reader who does
not follow one of the two languages needs a translation, and this module makes
one on request, segment by segment, with a local model.

**The model depends on the language** (``config.TRANSLATION_MODELS``): the
pipeline's qwen2.5:7b for English, and Aya Expanse for Hindi, because qwen's
written Hindi changed facts in testing (a date, a time of day).

**Not part of the evaluated pipeline.** A translation is a reading aid shown in
the UI and in exported transcripts. It is not a stage, does not enter the
config hash, and nothing in the evaluation reads it. It is stored beside the
run's artifacts (``translations/<target>.json``) with the model and prompt
version that made it, and with a fingerprint of the transcript it was made
from. It is treated as absent, and made again on request, when that transcript
is re-generated (a resume re-runs normalization) or when the configured model
or prompt has changed.

**Segments already in the target language are copied, not translated.** A
segment tagged English is already English, and one tagged Hindi is already
Hindi in its original Devanagari; sending those through the model could only
change words that were transcribed, never improve them.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from meeting_assistant import config
from meeting_assistant.errors import ArtifactError, LLMError
from meeting_assistant.io_utils import read_json, write_json
from meeting_assistant.llm.client import OllamaClient
from meeting_assistant.llm.prompts import ACTIVE_TRANSLATE_PROMPTS
from meeting_assistant.logging_setup import get_logger
from meeting_assistant.paths import RunPaths

log = get_logger(__name__)

Target = Literal["english", "hindi"]
TARGETS: tuple[Target, ...] = ("english", "hindi")

# The language tag that means a segment is already wholly in the target language.
_ALREADY = {"english": "English", "hindi": "Hindi"}
# Transcripts in the script they were spoken in, most processed first. The
# romanized ``hinglish`` artifact is used alongside, never instead.
ORIGINAL_CHAIN = ("tagged", "merged", "aligned")
# Stop early when the model is plainly unreachable, instead of failing every segment.
_GIVE_UP_AFTER = 3

ProgressCallback = Callable[[int, int], None]


def translation_path(paths: RunPaths, target: Target) -> Path:
    return paths.root / "translations" / f"{target}.json"


def _original_source(paths: RunPaths) -> str:
    for name in ORIGINAL_CHAIN:
        if paths.has(name):
            return name
    raise ArtifactError(f"Run {paths.run_id} has no transcript to translate yet")


def source_fingerprint(paths: RunPaths) -> str:
    """sha256 over the transcript files a translation is made from."""
    digest = hashlib.sha256()
    names = [_original_source(paths)] + (["hinglish"] if paths.has("hinglish") else [])
    for name in names:
        digest.update(name.encode())
        digest.update(paths.artifact(name).read_bytes())
    return digest.hexdigest()


def translation_model(target: Target) -> str:
    return config.TRANSLATION_MODELS[target]


def load_translation(paths: RunPaths, target: Target) -> dict[str, Any] | None:
    """The stored translation, or ``None`` if there is none for the current
    transcript, model and prompt."""
    path = translation_path(paths, target)
    if not path.is_file():
        return None
    try:
        document = read_json(path)
        current = source_fingerprint(paths)
    except (ArtifactError, OSError, ValueError):
        return None
    version, _ = ACTIVE_TRANSLATE_PROMPTS[target]
    if (
        document.get("source_fingerprint") != current
        or document.get("model") != translation_model(target)
        or document.get("prompt_version") != version
    ):
        return None
    return document


def _clean(reply: str) -> str:
    """The model's reply as one line, without a label or quotes around it."""
    text = " ".join(line.strip() for line in reply.splitlines() if line.strip())
    for label in ("Output:", "Translation:", "English:", "Hindi:"):
        if text.startswith(label):
            text = text[len(label) :].strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1].strip()
    return text


@dataclass
class TranslationResult:
    segments: list[dict[str, Any]]
    translated: int
    copied: int
    failed: int
    elapsed_sec: float


def translate_segments(
    original: list[dict[str, Any]],
    romanized: list[dict[str, Any]] | None,
    target: Target,
    client: OllamaClient,
    *,
    on_progress: ProgressCallback | None = None,
) -> TranslationResult:
    """Translate every segment's text; everything else in a segment is kept.

    Each output segment gains ``translation``: ``"translated"``, ``"copied"``
    (already in the target language) or ``"failed"`` (the original text is
    kept, so a reader sees what was said rather than a gap).

    Raises:
        LLMError: if the first few requests all fail -- the model is not
            reachable, and a translation made only of failures is not one.
    """
    _version, system_prompt = ACTIVE_TRANSLATE_PROMPTS[target]
    paired = romanized if romanized is not None and len(romanized) == len(original) else None
    started = time.perf_counter()
    out: list[dict[str, Any]] = []
    translated = copied = failed = 0
    total = len(original)

    for index, segment in enumerate(original):
        text = str(segment.get("text") or "").strip()
        roman = str(paired[index].get("text") or "").strip() if paired else ""
        result = dict(segment)
        if not text:
            result["translation"] = "copied"
            copied += 1
        elif segment.get("language") == _ALREADY[target]:
            # English is best read from the romanized copy, where English words
            # that Whisper spelled in Devanagari are back in Latin letters.
            result["text"] = (roman or text) if target == "english" else text
            result["translation"] = "copied"
            copied += 1
        else:
            prompt = f"Original: {text}"
            if roman and roman != text:
                prompt += f"\nRomanized: {roman}"
            try:
                reply = _clean(client.generate(prompt, system=system_prompt))
            except LLMError as exc:
                failed += 1
                if translated == 0 and failed >= _GIVE_UP_AFTER:
                    raise LLMError(f"Translation stopped: {exc}") from exc
                log.warning("Translation failed for segment %d, keeping the original", index)
                result["translation"] = "failed"
            else:
                if reply:
                    result["text"] = reply
                    result["translation"] = "translated"
                    translated += 1
                else:
                    result["translation"] = "failed"
                    failed += 1
        out.append(result)
        if on_progress is not None:
            on_progress(index + 1, total)

    elapsed = time.perf_counter() - started
    log.info(
        "Translated %d segment(s) to %s in %.1fs (%d copied, %d failed)",
        translated,
        target,
        elapsed,
        copied,
        failed,
    )
    return TranslationResult(out, translated, copied, failed, elapsed)


def build_translation(
    paths: RunPaths,
    target: Target,
    client: OllamaClient | None = None,
    *,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Translate the run's transcript and store it; returns the stored document."""
    client = client or OllamaClient(model=translation_model(target))
    source = _original_source(paths)
    fingerprint = source_fingerprint(paths)
    original = read_json(paths.artifact(source))
    romanized = read_json(paths.artifact("hinglish")) if paths.has("hinglish") else None

    result = translate_segments(original, romanized, target, client, on_progress=on_progress)
    version, _ = ACTIVE_TRANSLATE_PROMPTS[target]
    document = {
        "target": target,
        "model": client.model,
        "prompt_version": version,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_artifacts": [source] + (["hinglish"] if romanized is not None else []),
        "source_fingerprint": fingerprint,
        "segments_total": len(result.segments),
        "segments_translated": result.translated,
        "segments_copied": result.copied,
        "segments_failed": result.failed,
        "elapsed_sec": round(result.elapsed_sec, 2),
        "segments": result.segments,
    }
    path = translation_path(paths, target)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, document)
    return document
