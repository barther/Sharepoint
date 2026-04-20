"""SQLite schema for the archive.

The schema anticipates later slices: Core extraction fields live on `files` as
nullable columns from day one so pre-flight can populate `path`, `hash`,
`mime_type`, etc. without blocking a later migration to add
`document_type`, `proposed_folder`, and friends.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    path                   TEXT NOT NULL UNIQUE,
    relative_path          TEXT NOT NULL,
    filename               TEXT NOT NULL,
    extension              TEXT,
    size_bytes             INTEGER NOT NULL,
    mtime_utc              TEXT NOT NULL,
    sha256                 TEXT,
    mime_type              TEXT,

    -- Pre-flight assessment
    is_readable            INTEGER NOT NULL DEFAULT 1,  -- 0 if open/read raised
    is_empty               INTEGER NOT NULL DEFAULT 0,
    is_encrypted           INTEGER NOT NULL DEFAULT 0,
    extractable_text       INTEGER NOT NULL DEFAULT 0,
    extracted_char_count   INTEGER,
    needs_ocr              INTEGER NOT NULL DEFAULT 0,
    legibility_score       REAL,                         -- michelson contrast 0..1
    estimated_dpi          INTEGER,
    legibility_flag        TEXT,                         -- 'clean' | 'messy' | 'illegible' | NULL
    quarantine_reason      TEXT,                         -- NULL if not quarantined
    dup_of_sha256          TEXT,                         -- set when this file is an exact hash dup of another

    -- Later-slice fields (nullable placeholders for extraction pass)
    document_type          TEXT,
    title                  TEXT,
    summary_one_sentence   TEXT,
    date_primary           TEXT,
    date_primary_precision TEXT,
    condition              TEXT,
    proposed_folder        TEXT,
    proposed_filename      TEXT,
    confidence_identity    REAL,
    confidence_destination REAL,

    -- Run tracking
    first_seen_run_id      INTEGER,
    last_seen_run_id       INTEGER,
    FOREIGN KEY (first_seen_run_id) REFERENCES pre_flight_runs(id),
    FOREIGN KEY (last_seen_run_id)  REFERENCES pre_flight_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_files_sha256       ON files (sha256);
CREATE INDEX IF NOT EXISTS idx_files_quarantine   ON files (quarantine_reason);
CREATE INDEX IF NOT EXISTS idx_files_dup          ON files (dup_of_sha256);

CREATE TABLE IF NOT EXISTS pre_flight_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at_utc  TEXT NOT NULL,
    finished_at_utc TEXT,
    root_path       TEXT NOT NULL,
    files_scanned   INTEGER NOT NULL DEFAULT 0,
    files_new       INTEGER NOT NULL DEFAULT 0,
    files_skipped   INTEGER NOT NULL DEFAULT 0,
    files_failed    INTEGER NOT NULL DEFAULT 0,
    notes           TEXT
);

-- Later-slice placeholders; kept empty by pre-flight but defined now to avoid
-- migration churn when slice 2+ starts populating them.
CREATE TABLE IF NOT EXISTS exclusion_log (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    path                 TEXT NOT NULL,
    exclusion_reason     TEXT NOT NULL,
    exclusion_detail     TEXT,
    excluded_by          TEXT,
    excluded_date_utc    TEXT,
    board_authorization  TEXT,
    disposition          TEXT
);

CREATE TABLE IF NOT EXISTS moves_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id           INTEGER NOT NULL,
    source_path       TEXT NOT NULL,
    destination_path  TEXT NOT NULL,
    moved_at_utc      TEXT NOT NULL,
    approved_by       TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id)
);

CREATE TABLE IF NOT EXISTS model_routing_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id       INTEGER NOT NULL,
    model         TEXT NOT NULL,
    call_stage    TEXT NOT NULL,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL,
    called_at_utc TEXT NOT NULL,
    FOREIGN KEY (file_id) REFERENCES files(id)
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )
    conn.commit()


def get_schema_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = ?", ("schema_version",)
    ).fetchone()
    return int(row["value"]) if row else None
