"""Read-only queries over the run index.

Kept minimal for now — just enough for the CLI. Richer queries (filtering by
speaker, date range, language mix; full-text search over segments) are added
alongside the API layer that will actually need them, rather than speculatively
now.
"""

from __future__ import annotations

import sqlite3
from typing import Any


def list_runs(conn: sqlite3.Connection, *, limit: int | None = None) -> list[dict[str, Any]]:
    """All indexed runs, newest first."""
    sql = "SELECT * FROM runs ORDER BY created_at DESC"
    if limit is not None:
        sql += " LIMIT ?"
        rows = conn.execute(sql, (limit,)).fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    return [dict(row) for row in rows]


def get_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    """One run's indexed row, or ``None`` if it isn't in the index."""
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def count_runs(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
