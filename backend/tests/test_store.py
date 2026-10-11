"""Tests for the SQLite index: schema application, ingestion, and idempotency.

The filesystem run directories are the source of truth; this database exists
only to make cross-run queries fast. So the property that matters most here is
not any single query's correctness but that re-ingesting a run never
duplicates rows and always ends up reflecting exactly what is on disk right
now -- that is what makes ``meeting-assistant reindex`` a safe operation to run
at any time, including after a crash or a partially-deleted database.
"""

from __future__ import annotations

from meeting_assistant.io_utils import write_json
from meeting_assistant.paths import new_run
from meeting_assistant.store.db import open_db
from meeting_assistant.store.ingest import ingest_run, reindex_all
from meeting_assistant.store.queries import count_runs, get_run, list_runs


def _completed_run(runs_dir, run_id_source="meeting.wav", *, with_extras=True, captured_at=None):
    """Build a run directory with a manifest and artifacts, as a real batch
    run would leave behind -- without running any real stage."""
    paths = new_run("batch", run_id_source, runs_dir=runs_dir)

    manifest = {
        "run_id": paths.run_id,
        "mode": "batch",
        "status": "completed",
        "data_origin": "real_audio",
        "provenance": {
            "captured_at": captured_at or "2026-09-25T18:00:00",
            "finished_at": "2026-09-25T18:05:00",
            "config_hash": "abc123",
            "git": {"commit": "deadbeef", "dirty": False},
            "input": {"path": "data/audio/meeting.wav", "sha256": "feedface"},
        },
        "stages": [
            {
                "name": "transcript", "status": "ok", "seconds": 12.3,
                "outputs": [], "counts": {}, "error": None,
            },
            {
                "name": "aligned", "status": "ok", "seconds": 0.1,
                "outputs": [], "counts": {}, "error": None,
            },
        ],
        "extra": {},
    }
    write_json(paths.manifest_path, manifest)

    if with_extras:
        write_json(
            paths.artifact("hinglish"),
            [
                {
                    "start": 0.0, "end": 2.0, "speaker": "SPEAKER_00",
                    "language": "Hindi", "text": "namaste",
                },
                {
                    "start": 2.0, "end": 4.0, "speaker": "SPEAKER_01",
                    "language": "English", "text": "hello",
                },
            ],
        )
        write_json(
            paths.artifact("speaker_stats"),
            {
                "speakers": {
                    "SPEAKER_00": {
                        "speaking_time_sec": 2.0, "participation_pct": 50.0,
                        "utterance_count": 1, "word_count": 1,
                    },
                    "SPEAKER_01": {
                        "speaking_time_sec": 2.0, "participation_pct": 50.0,
                        "utterance_count": 1, "word_count": 1,
                    },
                },
                "totals": {"num_speakers": 2},
            },
        )
        write_json(
            paths.artifact("action_items"),
            {
                "action_items": [
                    {"person": "A", "task": "send notes", "deadline": "Friday", "status": None}
                ]
            },
        )
        write_json(
            paths.artifact("summary"),
            {"summary": "They said hello.", "highlights": ["greeting"], "key_decisions": []},
        )

    return paths


def test_apply_schema_is_idempotent(tmp_path):
    db_path = tmp_path / "index.sqlite"
    with open_db(db_path) as conn:
        conn.execute("SELECT COUNT(*) FROM runs")
    with open_db(db_path) as conn:  # second open must not fail on existing tables
        conn.execute("SELECT COUNT(*) FROM runs")


def test_ingest_run_with_no_manifest_returns_false(tmp_path):
    paths = new_run("batch", "x.wav", runs_dir=tmp_path / "runs")
    with open_db(tmp_path / "index.sqlite") as conn:
        assert ingest_run(conn, paths) is False
        assert count_runs(conn) == 0


def test_ingest_run_populates_the_runs_table(tmp_path):
    runs_dir = tmp_path / "runs"
    paths = _completed_run(runs_dir)
    with open_db(tmp_path / "index.sqlite") as conn:
        assert ingest_run(conn, paths) is True
        row = get_run(conn, paths.run_id)

    assert row is not None
    assert row["status"] == "completed"
    assert row["data_origin"] == "real_audio"
    assert row["git_commit"] == "deadbeef"
    assert row["config_hash"] == "abc123"


def test_ingest_run_populates_stage_timings(tmp_path):
    runs_dir = tmp_path / "runs"
    paths = _completed_run(runs_dir)
    with open_db(tmp_path / "index.sqlite") as conn:
        ingest_run(conn, paths)
        rows = conn.execute(
            "SELECT stage, status FROM stage_timings WHERE run_id = ? ORDER BY stage",
            (paths.run_id,),
        ).fetchall()
    assert [dict(r) for r in rows] == [
        {"stage": "aligned", "status": "ok"},
        {"stage": "transcript", "status": "ok"},
    ]


def test_ingest_run_populates_segments_from_the_best_available_artifact(tmp_path):
    runs_dir = tmp_path / "runs"
    paths = _completed_run(runs_dir)
    with open_db(tmp_path / "index.sqlite") as conn:
        ingest_run(conn, paths)
        rows = conn.execute(
            "SELECT speaker, language, text FROM segments WHERE run_id = ? ORDER BY idx",
            (paths.run_id,),
        ).fetchall()
    assert [dict(r) for r in rows] == [
        {"speaker": "SPEAKER_00", "language": "Hindi", "text": "namaste"},
        {"speaker": "SPEAKER_01", "language": "English", "text": "hello"},
    ]


def test_ingest_run_with_no_transcript_artifact_indexes_zero_segments(tmp_path):
    runs_dir = tmp_path / "runs"
    paths = _completed_run(runs_dir, with_extras=False)
    with open_db(tmp_path / "index.sqlite") as conn:
        ingest_run(conn, paths)
        count = conn.execute(
            "SELECT COUNT(*) FROM segments WHERE run_id = ?", (paths.run_id,)
        ).fetchone()[0]
    assert count == 0


def test_ingest_run_populates_speakers(tmp_path):
    runs_dir = tmp_path / "runs"
    paths = _completed_run(runs_dir)
    with open_db(tmp_path / "index.sqlite") as conn:
        ingest_run(conn, paths)
        rows = conn.execute(
            "SELECT speaker, participation_pct FROM speakers WHERE run_id = ? ORDER BY speaker",
            (paths.run_id,),
        ).fetchall()
    assert [dict(r) for r in rows] == [
        {"speaker": "SPEAKER_00", "participation_pct": 50.0},
        {"speaker": "SPEAKER_01", "participation_pct": 50.0},
    ]


def test_ingest_run_populates_action_items(tmp_path):
    runs_dir = tmp_path / "runs"
    paths = _completed_run(runs_dir)
    with open_db(tmp_path / "index.sqlite") as conn:
        ingest_run(conn, paths)
        row = conn.execute(
            "SELECT person, task, deadline FROM action_items WHERE run_id = ?", (paths.run_id,)
        ).fetchone()
    assert dict(row) == {"person": "A", "task": "send notes", "deadline": "Friday"}


def test_ingest_run_populates_summary_with_json_encoded_lists(tmp_path):
    runs_dir = tmp_path / "runs"
    paths = _completed_run(runs_dir)
    with open_db(tmp_path / "index.sqlite") as conn:
        ingest_run(conn, paths)
        row = conn.execute(
            "SELECT summary, highlights_json FROM summaries WHERE run_id = ?", (paths.run_id,)
        ).fetchone()
    assert row["summary"] == "They said hello."
    assert row["highlights_json"] == '["greeting"]'


def test_reingesting_a_run_does_not_duplicate_rows(tmp_path):
    """The core guarantee: reindex is always safe to run again."""
    runs_dir = tmp_path / "runs"
    paths = _completed_run(runs_dir)
    with open_db(tmp_path / "index.sqlite") as conn:
        ingest_run(conn, paths)
        ingest_run(conn, paths)
        ingest_run(conn, paths)

        assert count_runs(conn) == 1
        segment_count = conn.execute(
            "SELECT COUNT(*) FROM segments WHERE run_id = ?", (paths.run_id,)
        ).fetchone()[0]
    assert segment_count == 2


def test_reingesting_reflects_a_run_that_changed_on_disk(tmp_path):
    """A --force re-run's new artifacts must replace the old rows, not add to them."""
    runs_dir = tmp_path / "runs"
    paths = _completed_run(runs_dir)
    with open_db(tmp_path / "index.sqlite") as conn:
        ingest_run(conn, paths)

        # Simulate --force having produced a shorter transcript on re-run.
        write_json(
            paths.artifact("hinglish"),
            [
                {
                    "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00",
                    "language": "English", "text": "hi",
                }
            ],
        )
        ingest_run(conn, paths)

        rows = conn.execute(
            "SELECT text FROM segments WHERE run_id = ?", (paths.run_id,)
        ).fetchall()
    assert [dict(r)["text"] for r in rows] == ["hi"]


def test_reindex_all_reports_how_many_had_manifests(tmp_path):
    runs_dir = tmp_path / "runs"
    with_manifest = _completed_run(runs_dir, "a.wav")
    without_manifest = new_run("batch", "b.wav", runs_dir=runs_dir)

    from meeting_assistant.paths import list_runs as list_run_paths

    with open_db(tmp_path / "index.sqlite") as conn:
        count = reindex_all(conn, list_run_paths(runs_dir=runs_dir))

    assert count == 1
    assert without_manifest.run_id != with_manifest.run_id  # sanity: two distinct runs existed


def test_list_runs_orders_newest_first(tmp_path):
    """Ordering comes from each manifest's own captured_at, not disk mtime or
    insertion order -- so distinct explicit timestamps are enough here."""
    runs_dir = tmp_path / "runs"
    first = _completed_run(runs_dir, "a.wav", captured_at="2026-09-25T18:00:00")
    second = _completed_run(runs_dir, "b.wav", captured_at="2026-09-25T18:05:00")

    with open_db(tmp_path / "index.sqlite") as conn:
        ingest_run(conn, first)
        ingest_run(conn, second)
        rows = list_runs(conn)

    assert [r["run_id"] for r in rows] == [second.run_id, first.run_id]


def test_list_runs_respects_limit(tmp_path):
    runs_dir = tmp_path / "runs"
    with open_db(tmp_path / "index.sqlite") as conn:
        for i in range(3):
            ingest_run(conn, _completed_run(runs_dir, f"m{i}.wav"))
        rows = list_runs(conn, limit=2)
    assert len(rows) == 2


def test_get_run_returns_none_for_an_unindexed_run(tmp_path):
    with open_db(tmp_path / "index.sqlite") as conn:
        assert get_run(conn, "20200101-000000_batch_nope") is None


def test_deleting_a_run_cascades_to_child_tables(tmp_path):
    """Foreign keys with ON DELETE CASCADE must actually be enforced (PRAGMA)."""
    runs_dir = tmp_path / "runs"
    paths = _completed_run(runs_dir)
    with open_db(tmp_path / "index.sqlite") as conn:
        ingest_run(conn, paths)
        conn.execute("DELETE FROM runs WHERE run_id = ?", (paths.run_id,))
        remaining = conn.execute(
            "SELECT COUNT(*) FROM segments WHERE run_id = ?", (paths.run_id,)
        ).fetchone()[0]
    assert remaining == 0


def test_a_cross_thread_connection_can_be_closed_on_another_thread(tmp_path):
    """The API's per-request connection may be closed on a different pool
    thread than the one that opened it (see ``api.deps.get_db``)."""
    import threading

    from meeting_assistant.store.db import open_db

    errors: list[BaseException] = []
    context = open_db(tmp_path / "index.sqlite", cross_thread=True)
    conn = context.__enter__()
    conn.execute("SELECT 1")

    def close_elsewhere():
        try:
            context.__exit__(None, None, None)
        except BaseException as exc:  # noqa: BLE001 -- recorded for the assertion
            errors.append(exc)

    worker = threading.Thread(target=close_elsewhere)
    worker.start()
    worker.join()
    assert errors == []
