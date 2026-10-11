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
    owner: str | None = None,
) -> list[dict[str, Any]]:
    """Indexed runs, newest first, optionally filtered by status, mode and owner.

    ``owner`` is an ``accounts.User.uid``; ``None`` means every run (the CLI's
    view). The web API always passes the signed-in user's uid.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if owner is not None:
        clauses.append("owner = ?")
        params.append(owner)
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
    rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
    _add_overview(conn, rows)
    return rows


def _add_overview(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    """Attach what a meeting list shows at a glance, from the indexed artifacts.

    ``speakers`` (ordered by speaking time), ``duration_sec`` (end of the last
    segment) and ``language_mix`` (share of segment time per language tag) are
    read with one grouped query each for the whole page, never one per run.
    A run whose artifacts were not produced gets an empty list, ``None`` and an
    empty mapping -- absent, not zero.
    """
    for row in rows:
        row["speakers"] = []
        row["duration_sec"] = None
        row["language_mix"] = {}
    if not rows:
        return
    by_id = {row["run_id"]: row for row in rows}
    marks = ",".join("?" * len(by_id))
    ids = list(by_id)

    for run_id, speaker in conn.execute(
        f"SELECT run_id, speaker FROM speakers WHERE run_id IN ({marks}) "
        "ORDER BY run_id, speaking_time_sec DESC, speaker",
        ids,
    ):
        by_id[run_id]["speakers"].append(speaker)

    for run_id, end in conn.execute(
        f"SELECT run_id, MAX(end) FROM segments WHERE run_id IN ({marks}) GROUP BY run_id",
        ids,
    ):
        by_id[run_id]["duration_sec"] = end

    totals: dict[str, dict[str, float]] = {}
    for run_id, language, seconds in conn.execute(
        f"SELECT run_id, language, SUM(MAX(end - start, 0)) FROM segments "
        f"WHERE run_id IN ({marks}) AND language IS NOT NULL GROUP BY run_id, language",
        ids,
    ):
        totals.setdefault(run_id, {})[language] = seconds or 0.0
    for run_id, per_language in totals.items():
        whole = sum(per_language.values())
        if whole > 0:
            by_id[run_id]["language_mix"] = {
                language: round(seconds / whole, 4) for language, seconds in per_language.items()
            }


def get_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    """One run's indexed row, or ``None`` if it isn't in the index."""
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def count_runs(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


def _like_pattern(text: str) -> str:
    """``text`` as a LIKE substring pattern, with its wildcards taken literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_segments(
    conn: sqlite3.Connection, query: str, *, owner: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Transcript lines of ``owner``'s runs containing ``query``, newest runs first.

    A plain substring match (ASCII case-insensitive), over the same segments
    the run list's overview reads -- the most processed transcript of each run.
    """
    query = query.strip()
    if not query:
        return []
    rows = conn.execute(
        """
        SELECT s.run_id, s.idx, s.start, s.end, s.speaker, s.language, s.text,
               r.mode, r.created_at, r.audio_path
        FROM segments AS s JOIN runs AS r ON r.run_id = s.run_id
        WHERE r.owner = ? AND s.text LIKE ? ESCAPE '\\'
        ORDER BY r.created_at DESC, s.idx
        LIMIT ?
        """,
        (owner, _like_pattern(query), limit),
    ).fetchall()
    return [dict(row) for row in rows]

