"""Test-only launcher for the browser end-to-end test (``frontend/e2e``).

Serves the real FastAPI app and the built UI, but with every data directory in
a fresh temporary folder and the model pipeline replaced by a stub that writes
plausible artifacts stage by stage, with short pauses so the UI's progress
view is exercised. Nothing here touches ``data/`` or loads a model.

Every run it produces is stamped ``data_origin: "synthetic"``: it must never
be mistaken for a real result, and the UI's synthetic badge is part of what
the end-to-end test checks.

Usage (Playwright starts it; see ``frontend/playwright.config.ts``)::

    python backend/tests/e2e_server.py --port 8765

"""

from __future__ import annotations

import argparse
import shutil
import tempfile
import time
from pathlib import Path

STAGE_PAUSE_SEC = 0.25
# A recording whose name contains this gets a long transcript, so the browser
# test can exercise the transcript's virtualization with real layout.
LONG_MEETING_MARKER = "long"
LONG_MEETING_SEGMENTS = 400

SEGMENTS = [
    {"start": 0.0, "end": 3.2, "speaker": "SPEAKER_00", "language": "Hindi",
     "text": "namaste sabko, meeting shuru karte hain"},
    {"start": 3.2, "end": 7.5, "speaker": "SPEAKER_01", "language": "English",
     "text": "Let us review the release plan first"},
    {"start": 7.5, "end": 11.0, "speaker": "SPEAKER_00", "language": "Code-Mixed",
     "text": "release Friday ko hoga, testing kal tak"},
]
TAGGED = [
    {**SEGMENTS[0], "text": "नमस्ते सबको, मीटिंग शुरू करते हैं"},
    SEGMENTS[1],
    {**SEGMENTS[2], "text": "release Friday को होगा, testing कल तक"},
]


def _configure(root: Path) -> None:
    from meeting_assistant import config

    config.RUNS_DIR = root / "runs"
    config.AUDIO_DIR = root / "audio"
    config.EVAL_DIR = root / "eval"
    config.INDEX_DB_PATH = root / "index.sqlite"
    config.AUDIO_DIR.mkdir(parents=True)


def stub_batch(audio_path, opts):
    from meeting_assistant.io_utils import write_json
    from meeting_assistant.paths import open_run
    from meeting_assistant.pipeline.manifest import RunManifest

    paths = open_run(opts.resume_run_id)
    manifest = RunManifest.load(paths)
    manifest.data_origin = "synthetic"
    manifest.save()

    name = (manifest.provenance_block.get("input") or {}).get("name") or ""
    hinglish = SEGMENTS
    if LONG_MEETING_MARKER in name:
        hinglish = [
            {"start": i * 2.0, "end": i * 2.0 + 2.0, "speaker": f"SPEAKER_0{i % 2}",
             "language": "English", "text": f"long meeting line {i}"}
            for i in range(LONG_MEETING_SEGMENTS)
        ]

    outputs = {
        "transcript": {"segments": SEGMENTS, "language": "hi"},
        "diarization": [{"start": s["start"], "end": s["end"], "speaker": s["speaker"]}
                        for s in SEGMENTS],
        "aligned": SEGMENTS,
        "merged": SEGMENTS,
        "tagged": TAGGED,
        "speaker_stats": {
            "speakers": {
                "SPEAKER_00": {"speaking_time_sec": 6.7, "participation_pct": 60.9,
                               "utterance_count": 2, "word_count": 12,
                               "words_per_minute": 107.0, "mean_utterance_sec": 3.35},
                "SPEAKER_01": {"speaking_time_sec": 4.3, "participation_pct": 39.1,
                               "utterance_count": 1, "word_count": 7,
                               "words_per_minute": 98.0, "mean_utterance_sec": 4.3},
            },
            "totals": {"num_speakers": 2, "attributed_time_sec": 11.0,
                       "unattributed_time_sec": 0.0, "unattributed_pct": 0.0,
                       "total_speaking_time_sec": 11.0, "utterance_count": 3, "word_count": 19},
        },
        "metadata": {"meeting_id": paths.run_id, "date": "2026-10-01", "time": "16:00",
                     "duration_sec": 11.0, "duration_readable": "0m 11s", "num_speakers": 2,
                     "languages_used": ["Code-Mixed", "English", "Hindi"],
                     "total_word_count": 19, "segment_count": 3},
        "hinglish": hinglish,
        "summary": {"summary": "The team agreed to ship the release on Friday after testing.",
                    "highlights": ["Release planned for Friday"],
                    "key_decisions": ["Testing finishes tomorrow"]},
        "action_items": {"action_items": [{"person": "Diya", "task": "Finish testing",
                                           "deadline": "tomorrow"}]},
    }
    for name, artifact in outputs.items():
        time.sleep(STAGE_PAUSE_SEC)
        write_json(paths.artifact(name), artifact)
        manifest.record_stage(name, "ok", seconds=STAGE_PAUSE_SEC)
    manifest.set_status("completed")
    return paths


def stub_live(opts, *, paths, stop_event):
    from meeting_assistant.io_utils import write_json
    from meeting_assistant.pipeline.manifest import RunManifest

    manifest = RunManifest.load(paths)
    manifest.data_origin = "synthetic"
    manifest.save()
    segments = []
    while not stop_event.wait(timeout=0.4) and len(segments) < 300:
        n = len(segments)
        segments.append({"start": float(n), "end": n + 1.0, "speaker": "SPEAKER_G01",
                         "language": "English", "text": f"live chunk {n}"})
        write_json(paths.artifact("tagged"), segments)
    manifest.record_stage("tagged", "ok", seconds=0.1)
    manifest.set_extra("live_stats", {"chunks_recorded": len(segments),
                                      "chunks_processed": len(segments),
                                      "realtime_factor": 0.5})
    manifest.set_status("completed")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dist", type=Path, default=None, help="built UI (default: frontend/dist)")
    args = parser.parse_args()

    root = Path(tempfile.mkdtemp(prefix="meeting-assistant-e2e-"))
    try:
        _configure(root)

        import uvicorn

        from meeting_assistant import config
        from meeting_assistant.api.app import create_app
        from meeting_assistant.api.jobs import JobManager

        dist = args.dist or config.REPO_ROOT / "frontend" / "dist"
        app = create_app(
            jobs=JobManager(run_batch=stub_batch, run_live=stub_live),
            preload_models=False,
            frontend_dist=dist,
        )
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
