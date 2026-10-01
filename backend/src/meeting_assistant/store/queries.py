"""Read-only queries over the run index.

Only the filters the CLI and API actually use. Searching by speaker, language
mix or segment text is added when a screen needs it, not speculatively.
"""

from __future__ import annotations

import sqlite3
from typing import Any


def list_runs(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
    offset: int = 0,
    status: str | None = None,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    """Indexed runs, newest first, optionally filtered by status and mode."""
    clauses: list[str] = []
    params: list[Any] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if mode is not None:
        clauses.append("mode = ?")
        params.append(mode)

    sql = "SELECT * FROM runs"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def get_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    """One run's indexed row, or ``None`` if it isn't in the index."""
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def count_runs(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
