"""End-to-end tests for the pre-flight pipeline."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from church_archivist.preflight import (
    connect,
    initialize_schema,
    run_preflight,
    SCHEMA_VERSION,
)
from church_archivist.preflight.exclusions import (
    ExclusionConfigError,
    ExclusionRule,
    load as load_exclusions,
    match_first,
)
from church_archivist.preflight.schema import get_schema_version


def _rows(conn: sqlite3.Connection, sql: str, *params) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params).fetchall())


def test_schema_initializes(db_path: Path) -> None:
    conn = connect(db_path)
    initialize_schema(conn)
    assert get_schema_version(conn) == SCHEMA_VERSION
    tables = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    # All slice-1 + slice-2-placeholder tables exist.
    expected = {
        "files", "file_observations", "pre_flight_runs",
        "exclusion_log", "moves_log", "model_routing_log",
        "sensitive_flags", "evidence_quotes", "document_references",
        "decisions", "obligations", "policy_statements",
        "entities", "participants",
    }
    assert expected <= tables


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
    dups = _rows(
        conn,
        "SELECT relative_path, dup_of_file_id FROM files WHERE dup_of_file_id IS NOT NULL",
    )
    assert len(dups) == 1
    assert "20190421_bulletin_copy.pdf" in dups[0]["relative_path"]
    # The FK should point to the retained original, which exists in files.
    original = _rows(
        conn,
        "SELECT relative_path FROM files WHERE id = ?",
        dups[0]["dup_of_file_id"],
    )
    assert original and "20190421_bulletin.pdf" in original[0]["relative_path"]


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

    assert second.files_scanned == first.files_scanned
    assert second.files_new == 0
    assert second.files_skipped == first.files_scanned

    conn = connect(db_path)
    runs = _rows(conn, "SELECT COUNT(*) AS n FROM pre_flight_runs")
    assert runs[0]["n"] == 2

    files = _rows(conn, "SELECT COUNT(*) AS n FROM files")
    assert files[0]["n"] == first.files_scanned


def test_preflight_detects_modified_file(corpus_root: Path, db_path: Path) -> None:
    run_preflight(root=corpus_root, db_path=db_path)

    target = corpus_root / "présentation — été 2019.txt"
    target.write_text("Completely new content.\n", encoding="utf-8")

    second = run_preflight(root=corpus_root, db_path=db_path)
    assert second.files_new == 1
    assert second.files_skipped == second.files_scanned - 1


# ---------------------------------------------------------------------------
# file_observations history (#5)
# ---------------------------------------------------------------------------


def test_observation_recorded_per_run(corpus_root: Path, db_path: Path) -> None:
    run_preflight(root=corpus_root, db_path=db_path)
    run_preflight(root=corpus_root, db_path=db_path)

    conn = connect(db_path)
    # Two runs, every file observed in both runs.
    rows = _rows(
        conn,
        "SELECT file_id, COUNT(*) AS n FROM file_observations GROUP BY file_id",
    )
    assert rows, "observations should exist"
    assert all(r["n"] == 2 for r in rows), \
        "every file should have one observation per run"


def test_modified_file_keeps_prior_observation(corpus_root: Path, db_path: Path) -> None:
    run_preflight(root=corpus_root, db_path=db_path)

    target = corpus_root / "présentation — été 2019.txt"
    original_text = target.read_text(encoding="utf-8")
    target.write_text("Completely new content.\n", encoding="utf-8")

    run_preflight(root=corpus_root, db_path=db_path)

    conn = connect(db_path)
    file_id = _rows(
        conn, "SELECT id FROM files WHERE relative_path LIKE ?", "%présentation%"
    )[0]["id"]
    observations = _rows(
        conn,
        "SELECT sha256, run_id FROM file_observations WHERE file_id = ? ORDER BY run_id",
        file_id,
    )
    assert len(observations) == 2
    assert observations[0]["sha256"] != observations[1]["sha256"], \
        "observation hashes should differ after modification"


# ---------------------------------------------------------------------------
# Exclusion sweep (#1)
# ---------------------------------------------------------------------------


def _write_exclusion_config(path: Path, entries: list[dict]) -> Path:
    path.write_text(
        json.dumps({"version": 1, "exclusions": entries}, indent=2),
        encoding="utf-8",
    )
    return path


def test_exclusion_marks_files_and_writes_log(
    corpus_root: Path, db_path: Path, tmp_path: Path
) -> None:
    config = _write_exclusion_config(
        tmp_path / "exclusions.json",
        [
            {
                "match_type": "path_prefix",
                "match": "Pastoral Care/",
                "reason": "pastoral_care",
                "detail": "Counseling notes from active pastoral relationships",
                "excluded_by": "operator",
                "disposition": "retained_in_place",
            }
        ],
    )
    rules = load_exclusions(config)
    result = run_preflight(
        root=corpus_root,
        db_path=db_path,
        exclusion_rules=rules,
        exclusion_config_path=config,
    )
    assert result.excluded == 1

    conn = connect(db_path)
    excluded = _rows(
        conn,
        "SELECT relative_path, excluded, exclusion_reason FROM files WHERE excluded = 1",
    )
    assert len(excluded) == 1
    assert excluded[0]["exclusion_reason"] == "pastoral_care"
    assert excluded[0]["relative_path"].startswith("Pastoral Care/")

    log_rows = _rows(
        conn,
        "SELECT path, exclusion_reason, excluded_by, disposition, match_pattern "
        "FROM exclusion_log",
    )
    assert len(log_rows) == 1
    assert log_rows[0]["exclusion_reason"] == "pastoral_care"
    assert log_rows[0]["excluded_by"] == "operator"
    assert log_rows[0]["disposition"] == "retained_in_place"
    assert log_rows[0]["match_pattern"] == "path_prefix:Pastoral Care/"


def test_exclusion_glob_pattern(corpus_root: Path, db_path: Path, tmp_path: Path) -> None:
    config = _write_exclusion_config(
        tmp_path / "exclusions.json",
        [
            {
                "match_type": "glob",
                "match": "**/counseling_*.pdf",
                "reason": "pastoral_care",
            }
        ],
    )
    rules = load_exclusions(config)
    result = run_preflight(
        root=corpus_root,
        db_path=db_path,
        exclusion_rules=rules,
        exclusion_config_path=config,
    )
    assert result.excluded == 1


def test_exclusion_config_rejects_invalid_reason(tmp_path: Path) -> None:
    config = _write_exclusion_config(
        tmp_path / "bad.json",
        [{"match_type": "path_prefix", "match": "Foo/", "reason": "made_up_category"}],
    )
    with pytest.raises(ExclusionConfigError):
        load_exclusions(config)


def test_exclusion_config_rejects_invalid_match_type(tmp_path: Path) -> None:
    config = _write_exclusion_config(
        tmp_path / "bad.json",
        [{"match_type": "regex", "match": ".*", "reason": "pastoral_care"}],
    )
    with pytest.raises(ExclusionConfigError):
        load_exclusions(config)


def test_exclusion_rule_path_prefix_semantics() -> None:
    rule = ExclusionRule(
        match_type="path_prefix", match="Pastoral Care/", reason="pastoral_care"
    )
    assert rule.matches("Pastoral Care/notes.pdf")
    assert rule.matches("Pastoral Care/subfolder/notes.pdf")
    assert not rule.matches("Pastoral/notes.pdf")
    assert not rule.matches("Other/Pastoral Care/notes.pdf")


def test_exclusion_rule_glob_semantics() -> None:
    rule = ExclusionRule(
        match_type="glob", match="**/personnel_*.pdf", reason="personnel"
    )
    assert rule.matches("HR/personnel_evaluation.pdf")
    assert rule.matches("personnel_file.pdf")
    assert not rule.matches("HR/personnel_evaluation.docx")


def test_match_first_returns_none_when_no_match() -> None:
    rules = [
        ExclusionRule(match_type="path_prefix", match="Pastoral/", reason="pastoral_care"),
    ]
    assert match_first(rules, "Bulletins/easter.pdf") is None


# ---------------------------------------------------------------------------
# Unsupported / unrecognised format handling
# ---------------------------------------------------------------------------


def test_unsupported_formats_are_flagged(corpus_root: Path, db_path: Path) -> None:
    result = run_preflight(root=corpus_root, db_path=db_path)
    assert result.unsupported >= 5  # pub, xlsx, pptx, wpd, xyz

    conn = connect(db_path)
    by_ext = dict(
        (r["filename"], r["unsupported_format"])
        for r in _rows(
            conn,
            "SELECT filename, unsupported_format FROM files "
            "WHERE unsupported_format IS NOT NULL",
        )
    )
    assert by_ext["newsletter_spring_2018.pub"] == "publisher"
    assert by_ext["attendance_2019.xlsx"] == "spreadsheet"
    assert by_ext["service_slides_2019.pptx"] == "presentation"
    assert by_ext["rummage_sale_flyer.wpd"] == "wordperfect"
    assert by_ext["mystery.xyz"] == "unrecognized"


def test_unsupported_format_does_not_emit_processed(corpus_root: Path, db_path: Path) -> None:
    events: list[tuple[str, dict]] = []
    run_preflight(
        root=corpus_root,
        db_path=db_path,
        on_event=lambda kind, payload: events.append((kind, payload)),
    )
    pub_events = [
        (kind, payload)
        for kind, payload in events
        if payload.get("path", "").endswith("newsletter_spring_2018.pub")
    ]
    assert len(pub_events) == 1
    assert pub_events[0][0] == "unsupported"
    assert pub_events[0][1]["format"] == "publisher"


# ---------------------------------------------------------------------------
# Schema v2 placeholder tables (#2)
# ---------------------------------------------------------------------------


def test_schema_v2_relational_tables_accept_inserts(corpus_root: Path, db_path: Path) -> None:
    """Smoke-test that the §10-query tables actually accept FK-correct inserts.

    Slice 1 doesn't populate these, but if the schema is wrong we want to know
    before slice 2 starts writing into it.
    """
    run_preflight(root=corpus_root, db_path=db_path)
    conn = connect(db_path)
    file_id = _rows(conn, "SELECT id FROM files LIMIT 1")[0]["id"]

    conn.execute(
        "INSERT INTO sensitive_flags (file_id, category, severity, evidence_quote) "
        "VALUES (?, ?, ?, ?)",
        (file_id, "personnel", "low", "name mentioned in passing"),
    )
    conn.execute(
        "INSERT INTO decisions (file_id, content, assigned_to, status, evidence_quote) "
        "VALUES (?, ?, ?, ?, ?)",
        (file_id, "renew HVAC contract", "facilities committee", "open", "motion: …"),
    )
    conn.execute(
        "INSERT INTO policy_statements "
        "(file_id, content, effective_date, topic_canonical, evidence_quote) "
        "VALUES (?, ?, ?, ?, ?)",
        (file_id, "members must register annually", "2019-01-01", "membership_registration", "…"),
    )
    conn.execute(
        "INSERT INTO entities (kind, normalized_name) VALUES (?, ?)",
        ("committee", "Facilities Committee"),
    )
    conn.commit()

    counts = {
        t: _rows(conn, f"SELECT COUNT(*) AS n FROM {t}")[0]["n"]
        for t in ["sensitive_flags", "decisions", "policy_statements", "entities"]
    }
    assert all(n == 1 for n in counts.values())
