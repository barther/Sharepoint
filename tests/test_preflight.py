"""End-to-end tests for the pre-flight pipeline."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from church_archivist.preflight import (
    connect,
    initialize_schema,
    run_preflight,
    SCHEMA_VERSION,
)
from church_archivist.preflight.schema import get_schema_version


def _rows(conn: sqlite3.Connection, sql: str, *params) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params).fetchall())


def test_schema_initializes(db_path: Path) -> None:
    conn = connect(db_path)
    initialize_schema(conn)
    assert get_schema_version(conn) == SCHEMA_VERSION
    # All expected tables exist.
    tables = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {"files", "pre_flight_runs", "exclusion_log", "moves_log", "model_routing_log"} <= tables


def test_preflight_scans_all_files(corpus_root: Path, db_path: Path) -> None:
    result = run_preflight(root=corpus_root, db_path=db_path)

    assert result.files_scanned > 0
    assert result.files_new == result.files_scanned
    assert result.files_failed == 0

    conn = connect(db_path)
    rows = _rows(conn, "SELECT COUNT(*) AS n FROM files")
    assert rows[0]["n"] == result.files_scanned


def test_preflight_detects_hash_duplicate(corpus_root: Path, db_path: Path) -> None:
    run_preflight(root=corpus_root, db_path=db_path)
    conn = connect(db_path)
    dups = _rows(conn, "SELECT relative_path FROM files WHERE dup_of_sha256 IS NOT NULL")
    # The two copies of 20190421_bulletin.pdf should produce exactly one dup
    # entry (the second-seen copy is marked; the first retained).
    assert len(dups) == 1
    assert "20190421_bulletin_copy.pdf" in dups[0]["relative_path"]


def test_preflight_quarantines_zero_byte_and_corrupt(corpus_root: Path, db_path: Path) -> None:
    run_preflight(root=corpus_root, db_path=db_path)
    conn = connect(db_path)
    q = {
        (r["filename"], r["quarantine_reason"])
        for r in _rows(
            conn,
            "SELECT filename, quarantine_reason FROM files WHERE quarantine_reason IS NOT NULL",
        )
    }
    assert ("zero_byte.pdf", "empty") in q
    assert any(fn == "corrupt.pdf" and reason == "corrupt" for fn, reason in q)


def test_preflight_flags_password_protected(corpus_root: Path, db_path: Path) -> None:
    run_preflight(root=corpus_root, db_path=db_path)
    conn = connect(db_path)
    rows = _rows(
        conn,
        "SELECT quarantine_reason, is_encrypted FROM files WHERE filename = ?",
        "password_protected.pdf",
    )
    assert rows, "expected password_protected.pdf in the db"
    assert rows[0]["is_encrypted"] == 1
    assert rows[0]["quarantine_reason"] == "password-protected"


def test_preflight_flags_scan_needs_ocr(corpus_root: Path, db_path: Path) -> None:
    run_preflight(root=corpus_root, db_path=db_path)
    conn = connect(db_path)
    # JPEGs should always need OCR (they're image files with no text layer).
    rows = _rows(
        conn,
        "SELECT filename, needs_ocr FROM files WHERE filename LIKE '%.jpg'",
    )
    assert rows, "expected JPEG fixtures"
    assert all(r["needs_ocr"] == 1 for r in rows)


def test_preflight_legibility_split(corpus_root: Path, db_path: Path) -> None:
    run_preflight(root=corpus_root, db_path=db_path)
    conn = connect(db_path)
    low = _rows(
        conn,
        "SELECT legibility_flag FROM files WHERE filename = ?",
        "low_contrast_scan.jpg",
    )
    high = _rows(
        conn,
        "SELECT legibility_flag FROM files WHERE filename = ?",
        "high_contrast_page.jpg",
    )
    assert low and low[0]["legibility_flag"] in {"messy", "illegible"}
    assert high and high[0]["legibility_flag"] == "clean"


def test_preflight_extracts_text_from_pdf_and_docx(corpus_root: Path, db_path: Path) -> None:
    run_preflight(root=corpus_root, db_path=db_path)
    conn = connect(db_path)
    rows = _rows(
        conn,
        "SELECT filename, extractable_text, extracted_char_count "
        "FROM files WHERE filename IN (?, ?)",
        "20190421_bulletin.pdf",
        "2019_march_minutes.docx",
    )
    assert len(rows) == 2
    for r in rows:
        assert r["extractable_text"] == 1
        assert r["extracted_char_count"] > 0


def test_preflight_handles_unicode_filenames(corpus_root: Path, db_path: Path) -> None:
    run_preflight(root=corpus_root, db_path=db_path)
    conn = connect(db_path)
    rows = _rows(
        conn,
        "SELECT filename FROM files WHERE filename LIKE ?",
        "%présentation%",
    )
    assert rows, "unicode-named text file should round-trip into the db"


def test_preflight_is_idempotent(corpus_root: Path, db_path: Path) -> None:
    first = run_preflight(root=corpus_root, db_path=db_path)
    second = run_preflight(root=corpus_root, db_path=db_path)

    # Second run sees the same files but processes none as new.
    assert second.files_scanned == first.files_scanned
    assert second.files_new == 0
    assert second.files_skipped == first.files_scanned

    conn = connect(db_path)
    runs = _rows(conn, "SELECT COUNT(*) AS n FROM pre_flight_runs")
    assert runs[0]["n"] == 2

    # File count should not have doubled.
    files = _rows(conn, "SELECT COUNT(*) AS n FROM files")
    assert files[0]["n"] == first.files_scanned


def test_preflight_detects_modified_file(corpus_root: Path, db_path: Path) -> None:
    run_preflight(root=corpus_root, db_path=db_path)

    # Mutate one file so its hash changes.
    target = corpus_root / "présentation — été 2019.txt"
    target.write_text("Completely new content.\n", encoding="utf-8")

    second = run_preflight(root=corpus_root, db_path=db_path)
    assert second.files_new == 1  # just the modified file
    assert second.files_skipped == second.files_scanned - 1
