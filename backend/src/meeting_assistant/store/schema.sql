-- SQLite index over run artifacts.
--
-- The filesystem under data/runs/ remains the source of truth -- every table
-- here is rebuildable from artifacts and manifests on disk via `ingest_run`
-- (`meeting-assistant reindex` rebuilds the whole database this way). This
-- schema exists purely to make cross-run queries fast: "list every meeting",
-- "every action item assigned to X", "every run's WER" would each mean
-- reading and parsing every run directory on disk without it.
--
-- More tables (eval_results, experiments) are added in later phases, once the
-- modules that populate them exist -- an empty table with nothing to write to
-- it is a schema nobody has validated yet.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    mode         TEXT NOT NULL,               -- "batch" | "live"
    status       TEXT NOT NULL,                -- "completed" | "partial" | "failed"
    data_origin  TEXT NOT NULL,                -- "real_audio" | "synthetic"
    created_at   TEXT,
    finished_at  TEXT,
    git_commit   TEXT,
    config_hash  TEXT,
    audio_path   TEXT,
    audio_sha256 TEXT,
    ingested_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stage_timings (
    run_id  TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    stage   TEXT NOT NULL,
    status  TEXT NOT NULL,                     -- "ok" | "failed" | "skipped"
    seconds REAL,
    error   TEXT,
    PRIMARY KEY (run_id, stage)
);

CREATE TABLE IF NOT EXISTS segments (
    run_id   TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    idx      INTEGER NOT NULL,
    start    REAL,
    end      REAL,
    speaker  TEXT,
    language TEXT,
    text     TEXT,
    PRIMARY KEY (run_id, idx)
);

CREATE TABLE IF NOT EXISTS speakers (
    run_id            TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    speaker           TEXT NOT NULL,
    speaking_time_sec REAL,
    participation_pct REAL,
    utterance_count   INTEGER,
    word_count        INTEGER,
    PRIMARY KEY (run_id, speaker)
);

CREATE TABLE IF NOT EXISTS action_items (
    run_id   TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    idx      INTEGER NOT NULL,
    person   TEXT,
    task     TEXT,
    deadline TEXT,
    status   TEXT,
    PRIMARY KEY (run_id, idx)
);

CREATE TABLE IF NOT EXISTS summaries (
    run_id             TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
    summary            TEXT,
    highlights_json    TEXT,
    key_decisions_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at);
CREATE INDEX IF NOT EXISTS idx_action_items_person ON action_items(person);
