"""Pre-flight orchestration.

Walks a corpus, hashes every file, extracts text where possible, assesses
legibility for images and scan-like PDFs, and detects hash duplicates. All
results are persisted to SQLite. The runner is idempotent: re-running on the
same corpus skips files whose (path, sha256) already exist.
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
    on_event: EventCallback | None = None,
) -> PreflightResult:
    """Run a full pre-flight pass against `root`, persisting to `db_path`.

    `on_event(kind, payload)` is called for every significant event so the CLI
    can stream greppable output and a future GUI can drive a progress bar.
    """
    conn = connect(db_path)
    initialize_schema(conn)

    run_id = _start_run(conn, root)
    result = PreflightResult(run_id=run_id)

    def emit(kind: str, payload: dict) -> None:
        result.events.append((kind, payload))
        if on_event is not None:
            on_event(kind, payload)

    try:
        for sf in scan(root):
            result.files_scanned += 1
            outcome = _process_file(conn, run_id, sf)
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
                "SELECT quarantine_reason, dup_of_sha256, needs_ocr, legibility_flag, extractable_text "
                "FROM files WHERE path = ?",
                (str(sf.path),),
            ).fetchone()
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
            if row["dup_of_sha256"]:
                result.duplicates += 1
                emit(
                    "dedup",
                    {
                        "path": sf.relative_path,
                        "matches": row["dup_of_sha256"],
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


def _start_run(conn: sqlite3.Connection, root: Path) -> int:
    cur = conn.execute(
        "INSERT INTO pre_flight_runs (started_at_utc, root_path) VALUES (?, ?)",
        (_utcnow(), str(root.resolve())),
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
               files_failed    = ?
         WHERE id = ?
        """,
        (
            _utcnow(),
            result.files_scanned,
            result.files_new,
            result.files_skipped,
            result.files_failed,
            run_id,
        ),
    )


def _process_file(
    conn: sqlite3.Connection, run_id: int, sf: ScannedFile
) -> str:
    """Return one of: 'new', 'skipped', 'failed'."""
    existing = conn.execute(
        "SELECT id, sha256 FROM files WHERE path = ?", (str(sf.path),)
    ).fetchone()

    if existing is not None and existing["sha256"] == sf.sha256:
        # Unchanged file from a prior run. Bump last_seen and move on.
        conn.execute(
            "UPDATE files SET last_seen_run_id = ? WHERE id = ?",
            (run_id, existing["id"]),
        )
        return "skipped"

    try:
        ext_result = extract_text(sf.path)
        leg_result = assess_legibility(sf.path)
    except Exception:  # noqa: BLE001 - don't let one bad file kill the run
        return "failed"

    quarantine = _classify_quarantine(sf, ext_result.failure_reason)

    # Dedup: if another row already has this sha256, this file is a duplicate.
    dup_of = None
    if sf.sha256 and not sf.is_empty:
        prior = conn.execute(
            "SELECT sha256 FROM files WHERE sha256 = ? AND path != ? LIMIT 1",
            (sf.sha256, str(sf.path)),
        ).fetchone()
        if prior is not None:
            dup_of = sf.sha256

    # We intentionally don't set extractable_text=True for scan-only PDFs, even
    # though extract() returned needs_ocr=True with char_count=0. That's the
    # correct signal for model routing later.
    data = (
        str(sf.path),
        sf.relative_path,
        sf.filename,
        sf.extension,
        sf.size_bytes,
        sf.mtime_utc,
        sf.sha256,
        sf.mime_type,
        int(ext_result.is_readable),
        int(sf.is_empty),
        int(ext_result.is_encrypted),
        int(ext_result.extractable_text),
        ext_result.char_count,
        int(ext_result.needs_ocr),
        leg_result.contrast,
        leg_result.estimated_dpi,
        leg_result.flag if leg_result.flag != "not_applicable" else None,
        quarantine,
        dup_of,
        run_id,
        run_id,
    )

    if existing is None:
        conn.execute(
            """
            INSERT INTO files (
                path, relative_path, filename, extension, size_bytes, mtime_utc,
                sha256, mime_type, is_readable, is_empty, is_encrypted,
                extractable_text, extracted_char_count, needs_ocr,
                legibility_score, estimated_dpi, legibility_flag,
                quarantine_reason, dup_of_sha256,
                first_seen_run_id, last_seen_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            data,
        )
    else:
        # Same path, different hash: file was modified. Update in place.
        conn.execute(
            """
            UPDATE files SET
                relative_path = ?, filename = ?, extension = ?, size_bytes = ?,
                mtime_utc = ?, sha256 = ?, mime_type = ?, is_readable = ?,
                is_empty = ?, is_encrypted = ?, extractable_text = ?,
                extracted_char_count = ?, needs_ocr = ?, legibility_score = ?,
                estimated_dpi = ?, legibility_flag = ?, quarantine_reason = ?,
                dup_of_sha256 = ?, last_seen_run_id = ?
            WHERE id = ?
            """,
            (
                sf.relative_path, sf.filename, sf.extension, sf.size_bytes,
                sf.mtime_utc, sf.sha256, sf.mime_type,
                int(ext_result.is_readable), int(sf.is_empty),
                int(ext_result.is_encrypted), int(ext_result.extractable_text),
                ext_result.char_count, int(ext_result.needs_ocr),
                leg_result.contrast, leg_result.estimated_dpi,
                leg_result.flag if leg_result.flag != "not_applicable" else None,
                quarantine, dup_of, run_id, existing["id"],
            ),
        )
    return "new"
