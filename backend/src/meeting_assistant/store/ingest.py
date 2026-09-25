"""Load one run's filesystem artifacts into the SQLite index.

Idempotent by construction: ingesting a run first deletes every row that run
already owns, then re-inserts from what is on disk right now. That makes
``meeting-assistant reindex`` safe to run at any time — after a resumed run
adds new artifacts, after a ``--force`` re-run replaces old ones, or just to
recover from a deleted database — without ever accumulating duplicate or stale
rows. The filesystem is authoritative; this module's only job is to mirror it.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from meeting_assistant.io_utils import read_json
from meeting_assistant.logging_setup import get_logger
from meeting_assistant.paths import RunPaths
from meeting_assistant.pipeline.stages import resolve_intel_input

log = get_logger(__name__)

_CHILD_TABLES = ("stage_timings", "segments", "speakers", "action_items", "summaries")


def _delete_existing(conn: sqlite3.Connection, run_id: str) -> None:
    for table in _CHILD_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))  # noqa: S608 -- table name is from a fixed internal tuple, not user input
    conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))


def ingest_run(conn: sqlite3.Connection, run: RunPaths) -> bool:
    """Ingest one run's manifest and artifacts.

    Returns:
        ``False`` (and makes no changes) if the run has no manifest yet — it
        never started, or died before its first write. ``True`` otherwise.
    """
    if not run.manifest_path.exists():
        log.debug("Skipping %s: no manifest yet", run.run_id)
        return False

    manifest = read_json(run.manifest_path)
    _delete_existing(conn, run.run_id)

    prov = manifest.get("provenance", {}) or {}
    input_info = prov.get("input") or {}

    conn.execute(
        """
        INSERT INTO runs (
            run_id, mode, status, data_origin, created_at, finished_at,
            git_commit, config_hash, audio_path, audio_sha256, ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            manifest.get("run_id", run.run_id),
            manifest.get("mode"),
            manifest.get("status"),
            manifest.get("data_origin"),
            prov.get("captured_at"),
            prov.get("finished_at"),
            (prov.get("git") or {}).get("commit"),
            prov.get("config_hash"),
            input_info.get("path"),
            input_info.get("sha256"),
        ),
    )

    for stage in manifest.get("stages", []):
        conn.execute(
            """INSERT INTO stage_timings (run_id, stage, status, seconds, error)
               VALUES (?, ?, ?, ?, ?)""",
            (
                run.run_id,
                stage.get("name"),
                stage.get("status"),
                stage.get("seconds"),
                stage.get("error"),
            ),
        )

    _ingest_segments(conn, run)
    _ingest_speakers(conn, run)
    _ingest_action_items(conn, run)
    _ingest_summary(conn, run)

    return True


def _ingest_segments(conn: sqlite3.Connection, run: RunPaths) -> None:
    try:
        _name, segments = resolve_intel_input(run)
    except Exception:  # noqa: BLE001 -- no transcript-shaped artifact exists yet; nothing to index
        return

    rows: list[tuple[Any, ...]] = [
        (
            run.run_id,
            index,
            segment.get("start"),
            segment.get("end"),
            segment.get("speaker"),
            segment.get("language"),
            segment.get("text"),
        )
        for index, segment in enumerate(segments)
    ]
    conn.executemany(
        """INSERT INTO segments (run_id, idx, start, end, speaker, language, text)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )


def _ingest_speakers(conn: sqlite3.Connection, run: RunPaths) -> None:
    if not run.has("speaker_stats"):
        return
    stats = read_json(run.artifact("speaker_stats"))
    rows = [
        (
            run.run_id,
            speaker,
            values.get("speaking_time_sec"),
            values.get("participation_pct"),
            values.get("utterance_count"),
            values.get("word_count"),
        )
        for speaker, values in (stats.get("speakers") or {}).items()
    ]
    conn.executemany(
        """INSERT INTO speakers (run_id, speaker, speaking_time_sec, participation_pct,
                                  utterance_count, word_count)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )


def _ingest_action_items(conn: sqlite3.Connection, run: RunPaths) -> None:
    if not run.has("action_items"):
        return
    payload = read_json(run.artifact("action_items"))
    rows = [
        (
            run.run_id,
            index,
            item.get("person"),
            item.get("task"),
            item.get("deadline"),
            item.get("status"),
        )
        for index, item in enumerate(payload.get("action_items") or [])
    ]
    conn.executemany(
        """INSERT INTO action_items (run_id, idx, person, task, deadline, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )


def _ingest_summary(conn: sqlite3.Connection, run: RunPaths) -> None:
    if not run.has("summary"):
        return
    payload = read_json(run.artifact("summary"))
    conn.execute(
        """INSERT INTO summaries (run_id, summary, highlights_json, key_decisions_json)
           VALUES (?, ?, ?, ?)""",
        (
            run.run_id,
            payload.get("summary"),
            json.dumps(payload.get("highlights") or [], ensure_ascii=False),
            json.dumps(payload.get("key_decisions") or [], ensure_ascii=False),
        ),
    )


def reindex_all(conn: sqlite3.Connection, runs: list[RunPaths]) -> int:
    """Ingest every run in ``runs``. Returns how many had a manifest to ingest."""
    ingested = 0
    for run in runs:
        if ingest_run(conn, run):
            ingested += 1
    return ingested
