"""SQLite connection and schema management for the run index.

The database lives at ``data/index.sqlite`` by default. It holds nothing that
cannot be regenerated from the run directories under ``data/runs/`` — see
:mod:`meeting_assistant.store.ingest` — so losing or deleting it is an
inconvenience, never data loss.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from meeting_assistant import config


def _schema_sql() -> str:
    return resources.files("meeting_assistant.store").joinpath("schema.sql").read_text(
        encoding="utf-8"
    )


def connect(
    db_path: str | Path | None = None, *, cross_thread: bool = False
) -> sqlite3.Connection:
    """Open a connection with row access by column name and foreign keys enforced.

    ``cross_thread`` lifts sqlite3's same-thread check for a connection that is
    used by one request at a time but may be opened and closed on different
    threads (FastAPI runs a sync dependency's setup and teardown on whichever
    pool thread is free). It never makes sharing a connection safe.
    """
    path = Path(db_path) if db_path is not None else config.INDEX_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, check_same_thread=not cross_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create any tables/indexes that don't already exist. Safe to call repeatedly."""
    conn.executescript(_schema_sql())
    _add_owner_column(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_owner ON runs(owner)")
    conn.commit()


def _add_owner_column(conn: sqlite3.Connection) -> None:
    """Upgrade an index from before runs had owners.

    Fills the new column from each run's manifest, the authoritative copy, so
    the run list is right immediately rather than after a manual reindex.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
    if "owner" in columns:
        return
    from meeting_assistant.io_utils import read_json

    conn.execute("ALTER TABLE runs ADD COLUMN owner TEXT")
    for (run_id,) in conn.execute("SELECT run_id FROM runs").fetchall():
        manifest_path = config.RUNS_DIR / run_id / "manifest.json"
        if manifest_path.is_file():
            owner = read_json(manifest_path).get("owner")
            conn.execute("UPDATE runs SET owner = ? WHERE run_id = ?", (owner, run_id))


@contextmanager
def open_db(
    db_path: str | Path | None = None, *, cross_thread: bool = False
) -> Iterator[sqlite3.Connection]:
    """Open a connection with the schema applied, committing on a clean exit.

    Usage::

        with open_db() as conn:
            conn.execute(...)
    """
    conn = connect(db_path, cross_thread=cross_thread)
    try:
        apply_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()
