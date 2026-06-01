"""Pre-flight orchestration.

Walks a corpus, hashes every file, extracts text where possible, assesses
legibility for images and scan-like PDFs, applies the governance exclusion
sweep (§3 / §16), and detects hash duplicates. Each run writes a
`file_observations` history row per file so prior state survives in-place
updates. The runner is idempotent: re-running on the same corpus skips
files whose (path, sha256) already exist.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# pypdf writes a lot of chatter ("EOF marker not found", etc.) to the
# root logger when it encounters malformed PDFs. That noise breaks the
# line-per-event CLI contract, and the diagnostic information we actually
# care about is already captured in `ExtractResult.failure_reason`.
logging.getLogger("pypdf").setLevel(logging.ERROR)

from .exclusions import ExclusionRule, match_first
from .extract import extract as extract_text
from .legibility import assess as assess_legibility
from .schema import connect, initialize_schema
from .walker import ScannedFile, scan


EventCallback = Callable[[str, dict], None]


@dataclass
class PreflightResult:
    run_id: int
    files_scanned: int = 0
    files_new: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    quarantined: int = 0
    duplicates: int = 0
    needs_ocr: int = 0
    excluded: int = 0
    unsupported: int = 0
    events: list[tuple[str, dict]] = field(default_factory=list)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classify_quarantine(sf: ScannedFile, extract_failure: str | None) -> str | None:
    if sf.is_empty:
        return "empty"
    if extract_failure == "password-protected":
        return "password-protected"
    if extract_failure and extract_failure.startswith("PdfReadError"):
        return "corrupt"
    if extract_failure and not extract_failure.startswith("mammoth"):
        return "unreadable"
    return None


def run_preflight(
    root: Path,
    db_path: Path,
    *,
    exclusion_rules: list[ExclusionRule] | None = None,
    exclusion_config_path: Path | None = None,
    on_event: EventCallback | None = None,
) -> PreflightResult:
    """Run a full pre-flight pass against `root`, persisting to `db_path`."""
    rules = exclusion_rules or []
    conn = connect(db_path)
    initialize_schema(conn)

    run_id = _start_run(conn, root, exclusion_config_path)
    result = PreflightResult(run_id=run_id)

    def emit(kind: str, payload: dict) -> None:
        result.events.append((kind, payload))
        if on_event is not None:
            on_event(kind, payload)

    try:
        for sf in scan(root):
            result.files_scanned += 1
            outcome = _process_file(conn, run_id, sf, rules)
            if outcome == "skipped":
                result.files_skipped += 1
                emit("skipped", {"path": sf.relative_path, "sha256": sf.sha256})
                continue
            if outcome == "failed":
                result.files_failed += 1
                emit("failed", {"path": sf.relative_path})
                continue

            result.files_new += 1
            row = conn.execute(
                "SELECT quarantine_reason, dup_of_file_id, needs_ocr, "
                "legibility_flag, extractable_text, excluded, exclusion_reason, "
                "unsupported_format "
                "FROM files WHERE path = ?",
                (str(sf.path),),
            ).fetchone()
            if row["excluded"]:
                result.excluded += 1
                emit(
                    "excluded",
                    {
                        "path": sf.relative_path,
                        "reason": row["exclusion_reason"],
                    },
                )
                continue
            if row["quarantine_reason"]:
                result.quarantined += 1
                emit(
                    "quarantined",
                    {
                        "path": sf.relative_path,
                        "reason": row["quarantine_reason"],
                    },
                )
                continue
            if row["dup_of_file_id"]:
                result.duplicates += 1
                emit(
                    "dedup",
                    {
                        "path": sf.relative_path,
                        "matches_file_id": row["dup_of_file_id"],
                    },
                )
                continue
            if row["unsupported_format"]:
                result.unsupported += 1
                emit(
                    "unsupported",
                    {
                        "path": sf.relative_path,
                        "format": row["unsupported_format"],
                    },
                )
                continue
            if row["needs_ocr"]:
                result.needs_ocr += 1
            emit(
                "processed",
                {
                    "path": sf.relative_path,
                    "sha256": sf.sha256,
                    "extractable_text": bool(row["extractable_text"]),
                    "needs_ocr": bool(row["needs_ocr"]),
                    "legibility_flag": row["legibility_flag"],
                },
            )
        _finish_run(conn, run_id, result)
        conn.commit()
    finally:
        conn.close()
    return result


def _start_run(
    conn: sqlite3.Connection,
    root: Path,
    exclusion_config_path: Path | None,
) -> int:
    cur = conn.execute(
        "INSERT INTO pre_flight_runs (started_at_utc, root_path, exclusion_config_path) "
        "VALUES (?, ?, ?)",
        (
            _utcnow(),
            str(root.resolve()),
            str(exclusion_config_path) if exclusion_config_path else None,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def _finish_run(
    conn: sqlite3.Connection, run_id: int, result: PreflightResult
) -> None:
    conn.execute(
        """
        UPDATE pre_flight_runs
           SET finished_at_utc = ?,
               files_scanned   = ?,
               files_new       = ?,
               files_skipped   = ?,
               files_failed    = ?,
               files_excluded  = ?
         WHERE id = ?
        """,
        (
            _utcnow(),
            result.files_scanned,
            result.files_new,
            result.files_skipped,
            result.files_failed,
            result.excluded,
            run_id,
        ),
    )


def _process_file(
    conn: sqlite3.Connection,
    run_id: int,
    sf: ScannedFile,
    rules: list[ExclusionRule],
) -> str:
    """Return one of: 'new', 'skipped', 'failed'."""
    existing = conn.execute(
        "SELECT id, sha256 FROM files WHERE path = ?", (str(sf.path),)
    ).fetchone()

    if existing is not None and existing["sha256"] == sf.sha256:
        conn.execute(
            "UPDATE files SET last_seen_run_id = ? WHERE id = ?",
            (run_id, existing["id"]),
        )
        # Even on a skipped file we record an observation so the audit log
        # captures "this file was seen during this run".
        _insert_observation(conn, existing["id"], run_id, sf, None, None, None)
        return "skipped"

    try:
        ext_result = extract_text(sf.path)
        leg_result = assess_legibility(sf.path)
    except Exception:  # noqa: BLE001 - don't let one bad file kill the run
        return "failed"

    quarantine = _classify_quarantine(sf, ext_result.failure_reason)

    matched_rule = match_first(rules, sf.relative_path)

    # Dedup uses file_id, not the raw hash, so callers can navigate to the
    # retained original via FK rather than re-querying by sha256.
    dup_of_file_id = None
    if sf.sha256 and not sf.is_empty:
        prior = conn.execute(
            "SELECT id FROM files WHERE sha256 = ? AND path != ? LIMIT 1",
            (sf.sha256, str(sf.path)),
        ).fetchone()
        if prior is not None:
            dup_of_file_id = prior["id"]

    file_id = _upsert_file(
        conn,
        existing,
        sf,
        ext_result,
        leg_result,
        quarantine,
        dup_of_file_id,
        matched_rule,
        run_id,
    )

    _insert_observation(
        conn,
        file_id,
        run_id,
        sf,
        ext_result.char_count,
        leg_result,
        quarantine,
    )

    if matched_rule is not None:
        _insert_exclusion_log(conn, file_id, sf, matched_rule)

    return "new"


def _upsert_file(
    conn: sqlite3.Connection,
    existing: sqlite3.Row | None,
    sf: ScannedFile,
    ext_result,
    leg_result,
    quarantine: str | None,
    dup_of_file_id: int | None,
    matched_rule: ExclusionRule | None,
    run_id: int,
) -> int:
    excluded = 1 if matched_rule is not None else 0
    exclusion_reason = matched_rule.reason if matched_rule is not None else None
    leg_flag = leg_result.flag if leg_result.flag != "not_applicable" else None

    if existing is None:
        cur = conn.execute(
            """
            INSERT INTO files (
                path, relative_path, filename, extension, size_bytes, mtime_utc,
                sha256, mime_type, is_readable, is_empty, is_encrypted,
                extractable_text, extracted_char_count, needs_ocr,
                legibility_score, estimated_dpi, legibility_flag,
                quarantine_reason, unsupported_format,
                dup_of_file_id, excluded, exclusion_reason,
                first_seen_run_id, last_seen_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(sf.path), sf.relative_path, sf.filename, sf.extension,
                sf.size_bytes, sf.mtime_utc, sf.sha256, sf.mime_type,
                int(ext_result.is_readable), int(sf.is_empty),
                int(ext_result.is_encrypted), int(ext_result.extractable_text),
                ext_result.char_count, int(ext_result.needs_ocr),
                leg_result.contrast, leg_result.estimated_dpi, leg_flag,
                quarantine, ext_result.unsupported_format,
                dup_of_file_id, excluded, exclusion_reason,
                run_id, run_id,
            ),
        )
        return int(cur.lastrowid)

    # Same path, different hash: file was modified. Update in place; history
    # is preserved via file_observations.
    conn.execute(
        """
        UPDATE files SET
            relative_path = ?, filename = ?, extension = ?, size_bytes = ?,
            mtime_utc = ?, sha256 = ?, mime_type = ?, is_readable = ?,
            is_empty = ?, is_encrypted = ?, extractable_text = ?,
            extracted_char_count = ?, needs_ocr = ?, legibility_score = ?,
            estimated_dpi = ?, legibility_flag = ?, quarantine_reason = ?,
            unsupported_format = ?, dup_of_file_id = ?, excluded = ?,
            exclusion_reason = ?, last_seen_run_id = ?
        WHERE id = ?
        """,
        (
            sf.relative_path, sf.filename, sf.extension, sf.size_bytes,
            sf.mtime_utc, sf.sha256, sf.mime_type,
            int(ext_result.is_readable), int(sf.is_empty),
            int(ext_result.is_encrypted), int(ext_result.extractable_text),
            ext_result.char_count, int(ext_result.needs_ocr),
            leg_result.contrast, leg_result.estimated_dpi, leg_flag,
            quarantine, ext_result.unsupported_format, dup_of_file_id,
            excluded, exclusion_reason, run_id, existing["id"],
        ),
    )
    return int(existing["id"])


def _insert_observation(
    conn: sqlite3.Connection,
    file_id: int,
    run_id: int,
    sf: ScannedFile,
    char_count: int | None,
    leg_result,
    quarantine: str | None,
) -> None:
    leg_flag = leg_result.flag if leg_result and leg_result.flag != "not_applicable" else None
    leg_score = leg_result.contrast if leg_result else None
    conn.execute(
        """
        INSERT INTO file_observations (
            file_id, run_id, observed_at_utc, sha256, size_bytes, mtime_utc,
            extracted_char_count, needs_ocr, legibility_score, legibility_flag,
            quarantine_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            run_id,
            _utcnow(),
            sf.sha256,
            sf.size_bytes,
            sf.mtime_utc,
            char_count,
            0 if leg_result is None else 0,  # observation row inherits from files later
            leg_score,
            leg_flag,
            quarantine,
        ),
    )


def _insert_exclusion_log(
    conn: sqlite3.Connection,
    file_id: int,
    sf: ScannedFile,
    rule: ExclusionRule,
) -> None:
    conn.execute(
        """
        INSERT INTO exclusion_log (
            file_id, path, exclusion_reason, exclusion_detail, excluded_by,
            excluded_date_utc, board_authorization, disposition, match_pattern
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            sf.relative_path,
            rule.reason,
            rule.detail,
            rule.excluded_by,
            _utcnow(),
            rule.board_authorization,
            rule.disposition,
            f"{rule.match_type}:{rule.match}",
        ),
    )
