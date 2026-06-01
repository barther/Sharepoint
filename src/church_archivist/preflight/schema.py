"""SQLite schema for the archive.

Schema version 2 adds the relational structures required by the §10
acceptance criteria (references, decisions, obligations, policy_statements,
sensitive_flags, evidence_quotes, entities, participants), a
file_observations history table so per-run state survives modification,
and explicit exclusion tracking (governance-driven, distinct from
quarantine).

The pre-flight pass populates only what it actually computes locally:
files, file_observations, exclusion_log entries when a config matches.
Relational extraction tables stay empty until slice 2 (Haiku pre-class +
deep read) writes into them. Defining them now avoids painful migrations
later — SQLite ALTER TABLE is narrow, and once production data exists,
restructuring becomes expensive.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per physical file currently observed in the corpus.
-- file_observations holds the per-run history; files holds the latest state.
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
    is_readable            INTEGER NOT NULL DEFAULT 1,
    is_empty               INTEGER NOT NULL DEFAULT 0,
    is_encrypted           INTEGER NOT NULL DEFAULT 0,
    extractable_text       INTEGER NOT NULL DEFAULT 0,
    extracted_char_count   INTEGER,
    needs_ocr              INTEGER NOT NULL DEFAULT 0,
    legibility_score       REAL,
    estimated_dpi          INTEGER,
    legibility_flag        TEXT,
    quarantine_reason      TEXT,                    -- technical: empty/corrupt/encrypted
    dup_of_file_id         INTEGER,                 -- FK to the retained original

    -- Governance: see §3 exclusion policy and §16 exclusion log.
    -- Set when a file matches an exclusion config entry; the canonical record
    -- lives in exclusion_log. These columns are a denormalised cache so
    -- downstream code can filter excluded files with a single column read.
    excluded               INTEGER NOT NULL DEFAULT 0,
    exclusion_reason       TEXT,

    -- Slice 2+ extraction fields (populated by model passes, not pre-flight).
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
    audience_restriction_recommended TEXT,
    belongs_in_archive     INTEGER,
    authenticity_markers   TEXT,

    -- Run tracking
    first_seen_run_id      INTEGER,
    last_seen_run_id       INTEGER,
    FOREIGN KEY (dup_of_file_id)    REFERENCES files(id),
    FOREIGN KEY (first_seen_run_id) REFERENCES pre_flight_runs(id),
    FOREIGN KEY (last_seen_run_id)  REFERENCES pre_flight_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_files_sha256       ON files (sha256);
CREATE INDEX IF NOT EXISTS idx_files_quarantine   ON files (quarantine_reason);
CREATE INDEX IF NOT EXISTS idx_files_dup          ON files (dup_of_file_id);
CREATE INDEX IF NOT EXISTS idx_files_excluded     ON files (excluded);

-- Per-run history of every file observation. Lets the runner update files in
-- place while preserving the audit trail required by §5 / §10.
CREATE TABLE IF NOT EXISTS file_observations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id           INTEGER NOT NULL,
    run_id            INTEGER NOT NULL,
    observed_at_utc   TEXT NOT NULL,
    sha256            TEXT,
    size_bytes        INTEGER NOT NULL,
    mtime_utc         TEXT NOT NULL,
    extracted_char_count INTEGER,
    needs_ocr         INTEGER NOT NULL DEFAULT 0,
    legibility_score  REAL,
    legibility_flag   TEXT,
    quarantine_reason TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id),
    FOREIGN KEY (run_id)  REFERENCES pre_flight_runs(id)
);
CREATE INDEX IF NOT EXISTS idx_observations_file ON file_observations (file_id);
CREATE INDEX IF NOT EXISTS idx_observations_run  ON file_observations (run_id);

CREATE TABLE IF NOT EXISTS pre_flight_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at_utc  TEXT NOT NULL,
    finished_at_utc TEXT,
    root_path       TEXT NOT NULL,
    exclusion_config_path TEXT,
    files_scanned   INTEGER NOT NULL DEFAULT 0,
    files_new       INTEGER NOT NULL DEFAULT 0,
    files_skipped   INTEGER NOT NULL DEFAULT 0,
    files_failed    INTEGER NOT NULL DEFAULT 0,
    files_excluded  INTEGER NOT NULL DEFAULT 0,
    notes           TEXT
);

-- §16 Formal Exclusion Log. One row per file marked for governance exclusion.
-- Populated by the exclusion sweep during pre-flight.
CREATE TABLE IF NOT EXISTS exclusion_log (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id              INTEGER,
    path                 TEXT NOT NULL,
    exclusion_reason     TEXT NOT NULL,
    exclusion_detail     TEXT,
    excluded_by          TEXT,
    excluded_date_utc    TEXT NOT NULL,
    board_authorization  TEXT,
    disposition          TEXT,
    match_pattern        TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id)
);
CREATE INDEX IF NOT EXISTS idx_exclusion_path ON exclusion_log (path);

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

-- ---------------------------------------------------------------------------
-- Relational extraction tables (populated by slice 2+; empty under pre-flight).
-- Defined here so the §10 SQL-answerable queries can be wired up without
-- requiring a migration once real extraction data lands.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sensitive_flags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL,
    category        TEXT NOT NULL,        -- pastoral_care, giving, medical, etc.
    severity        TEXT NOT NULL,        -- low / medium / high
    evidence_quote  TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id)
);
CREATE INDEX IF NOT EXISTS idx_sensitive_file ON sensitive_flags (file_id);

CREATE TABLE IF NOT EXISTS evidence_quotes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL,
    supports_field  TEXT NOT NULL,        -- identity / date / type / other
    quote           TEXT NOT NULL,
    page_or_offset  TEXT,
    FOREIGN KEY (file_id) REFERENCES files(id)
);
CREATE INDEX IF NOT EXISTS idx_evidence_file ON evidence_quotes (file_id);

-- §10 query "what documents are referenced but missing?"
CREATE TABLE IF NOT EXISTS document_references (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file_id      INTEGER NOT NULL,
    target_file_id      INTEGER,                  -- NULL when target unresolved
    target_description  TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'unresolved', -- resolved / unresolved
    evidence_quote      TEXT,
    FOREIGN KEY (source_file_id) REFERENCES files(id),
    FOREIGN KEY (target_file_id) REFERENCES files(id)
);
CREATE INDEX IF NOT EXISTS idx_references_status ON document_references (status);

-- §10 query "what commitments are open?" — decisions captured in minutes etc.
CREATE TABLE IF NOT EXISTS decisions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id             INTEGER NOT NULL,
    content             TEXT NOT NULL,
    assigned_to         TEXT,
    due_date            TEXT,
    status              TEXT NOT NULL DEFAULT 'unknown', -- open / closed / superseded / unknown
    closed_by_file_id   INTEGER,
    evidence_quote      TEXT,
    FOREIGN KEY (file_id)           REFERENCES files(id),
    FOREIGN KEY (closed_by_file_id) REFERENCES files(id)
);
CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions (status);

CREATE TABLE IF NOT EXISTS obligations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id             INTEGER NOT NULL,
    content             TEXT NOT NULL,
    assigned_to         TEXT,
    due_date            TEXT,
    status              TEXT NOT NULL DEFAULT 'unknown',
    closed_by_file_id   INTEGER,
    evidence_quote      TEXT,
    FOREIGN KEY (file_id)           REFERENCES files(id),
    FOREIGN KEY (closed_by_file_id) REFERENCES files(id)
);
CREATE INDEX IF NOT EXISTS idx_obligations_status ON obligations (status);

-- §10 query "where does the archive contradict itself?"
CREATE TABLE IF NOT EXISTS policy_statements (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id               INTEGER NOT NULL,
    content               TEXT NOT NULL,
    effective_date        TEXT,
    superseded_by_file_id INTEGER,
    topic_canonical       TEXT,
    evidence_quote        TEXT,
    FOREIGN KEY (file_id)               REFERENCES files(id),
    FOREIGN KEY (superseded_by_file_id) REFERENCES files(id)
);
CREATE INDEX IF NOT EXISTS idx_policy_topic ON policy_statements (topic_canonical);

-- Normalised entities: people, committees, organisations, properties, topics.
CREATE TABLE IF NOT EXISTS entities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL,        -- person / committee / organization / property / topic
    normalized_name TEXT NOT NULL,
    raw_names_json  TEXT,                 -- JSON array of source-text variants
    UNIQUE (kind, normalized_name)
);

CREATE TABLE IF NOT EXISTS participants (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id     INTEGER NOT NULL,
    entity_id   INTEGER NOT NULL,
    role        TEXT,                     -- author / signatory / mentioned / etc.
    FOREIGN KEY (file_id)   REFERENCES files(id),
    FOREIGN KEY (entity_id) REFERENCES entities(id)
);
CREATE INDEX IF NOT EXISTS idx_participants_file   ON participants (file_id);
CREATE INDEX IF NOT EXISTS idx_participants_entity ON participants (entity_id);
"""


class SchemaVersionMismatch(RuntimeError):
    """Raised when an existing database was created by an incompatible schema."""


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create the schema on a fresh db, or verify version on an existing one.

    No in-place migrations are implemented yet. If an older schema is found
    in a non-empty db, we raise — better than silently corrupting data.
    """
    existing = _existing_schema_version(conn)
    if existing is not None and existing != SCHEMA_VERSION:
        raise SchemaVersionMismatch(
            f"database has schema_version={existing} but code expects "
            f"{SCHEMA_VERSION}. delete archive.sqlite and re-run, or write "
            f"a migration."
        )
    conn.executescript(_SCHEMA_SQL)
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )
    conn.commit()


def _existing_schema_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_meta'"
    ).fetchone()
    if row is None:
        return None
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = ?", ("schema_version",)
    ).fetchone()
    return int(row["value"]) if row else None


def get_schema_version(conn: sqlite3.Connection) -> int | None:
    return _existing_schema_version(conn)
