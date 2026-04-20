"""Command-line entry point.

Slice-1 exposes the pre-flight pipeline only. Output is one line per
significant event, shell-friendly for tail/grep while debugging. The Tkinter
GUI will later replace this surface; in the meantime this is how the tool is
driven.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .preflight import run_preflight


def _print_event(kind: str, payload: dict) -> None:
    parts = [f"{kind}: {payload.get('path', '')}"]
    detail_keys = [k for k in payload.keys() if k != "path"]
    if detail_keys:
        detail = " ".join(f"{k}={payload[k]}" for k in detail_keys)
        parts.append(f"({detail})")
    print(" ".join(parts))


def _cmd_preflight(args: argparse.Namespace) -> int:
    root = Path(args.corpus).expanduser().resolve()
    if not root.is_dir():
        print(f"error: corpus path is not a directory: {root}", file=sys.stderr)
        return 2

    db_path = Path(args.db).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    result = run_preflight(
        root=root,
        db_path=db_path,
        on_event=None if args.quiet else _print_event,
    )

    print(
        f"summary: scanned={result.files_scanned} "
        f"new={result.files_new} "
        f"skipped={result.files_skipped} "
        f"failed={result.files_failed} "
        f"quarantined={result.quarantined} "
        f"duplicates={result.duplicates} "
        f"needs_ocr={result.needs_ocr} "
        f"run_id={result.run_id}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="church-archivist",
        description="Church archive tool (slice 1: pre-flight only).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("preflight", help="Run pre-flight pipeline against a corpus.")
    p.add_argument("corpus", help="Root directory of the corpus to scan.")
    p.add_argument(
        "--db",
        default="archive.sqlite",
        help="Path to the SQLite database (default: ./archive.sqlite).",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-file events; print only the summary line.",
    )
    p.set_defaults(func=_cmd_preflight)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
