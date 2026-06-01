"""Mixed-nasty fixture corpus.

The corpus is generated synthetically per-test rather than checked in, which
keeps the repo small and makes the ugly cases visible in code. The intent is
to exercise: zero-byte, corrupt PDF, password-protected PDF, scan-like PDF
with low contrast, unicode filenames, exact hash duplicates, and a JPEG
"photo of a document."

Dependencies (reportlab, python-docx, Pillow, numpy, pypdf, opencv) are
imported at module level. If any are missing, pytest reports a collection
error rather than silently skipping every test — this prevents a fresh
clone from reporting a green test suite while exercising nothing.
"""

from __future__ import annotations

import io
import os
import shutil
from pathlib import Path

import pytest

# Hard imports: missing dev deps must fail collection, not silently skip.
import numpy as np
from PIL import Image
from docx import Document
from pypdf import PdfWriter
from reportlab.pdfgen import canvas


# ---------------------------------------------------------------------------
# Builders for each nasty case. Each returns the filename it wrote.
# ---------------------------------------------------------------------------


def _write_zero_byte(root: Path) -> str:
    name = "zero_byte.pdf"
    (root / name).touch()
    return name


def _write_corrupt_pdf(root: Path) -> str:
    name = "corrupt.pdf"
    # Looks like a PDF header but the body is junk.
    (root / name).write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nnot a real pdf body\n")
    return name


def _write_password_protected_pdf(root: Path) -> str:
    name = "password_protected.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("hunter2")
    with (root / name).open("wb") as fh:
        writer.write(fh)
    return name


def _write_text_pdf(root: Path, filename: str, body: str) -> str:
    path = root / filename
    c = canvas.Canvas(str(path))
    text = c.beginText(72, 720)
    for line in body.splitlines() or [body]:
        text.textLine(line)
    c.drawText(text)
    c.showPage()
    c.save()
    return filename


def _write_low_contrast_jpeg(root: Path) -> str:
    name = "low_contrast_scan.jpg"
    # Almost uniform gray: michelson contrast will be near-zero.
    arr = np.full((400, 300), 128, dtype=np.uint8)
    arr[100:110, 50:250] = 140  # faint stripe so it isn't literally uniform
    Image.fromarray(arr).save(root / name)
    return name


def _write_high_contrast_jpeg(root: Path) -> str:
    name = "high_contrast_page.jpg"
    # Black text on white: high michelson contrast.
    arr = np.full((3300, 2550), 255, dtype=np.uint8)  # roughly 300 dpi @ letter
    arr[500:600, 500:2000] = 0
    arr[800:900, 500:2000] = 0
    Image.fromarray(arr).save(root / name)
    return name


def _write_docx(root: Path, filename: str, body: str) -> str:
    doc = Document()
    for line in body.splitlines() or [body]:
        doc.add_paragraph(line)
    doc.save(str(root / filename))
    return filename


def _write_unicode_named_text(root: Path) -> str:
    name = "présentation — été 2019.txt"
    (root / name).write_text(
        "Résumé of the 2019 summer presentation. Attendance forty-two.\n"
        "Budget exceeded by three hundred dollars.\n",
        encoding="utf-8",
    )
    return name


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def corpus_root(tmp_path: Path) -> Path:
    """A mixed-nasty fixture corpus laid out as a small SharePoint library."""
    root = tmp_path / "corpus"
    root.mkdir()

    # Nested structure so path handling gets exercised.
    (root / "Bulletins").mkdir()
    (root / "Minutes").mkdir()
    (root / "Scans").mkdir()
    (root / "Pastoral Care").mkdir()

    _write_text_pdf(
        root / "Bulletins",
        "20190421_bulletin.pdf",
        "Bulletin for Easter Sunday April 21 2019. Hymn 203. Sermon: Resurrection.",
    )
    _write_text_pdf(
        root / "Bulletins",
        "20190428_bulletin.pdf",
        "Bulletin for Sunday April 28 2019. Hymn 117. Sermon: Discipleship.",
    )

    _write_docx(
        root / "Minutes",
        "2019_march_minutes.docx",
        "Board meeting March 2019. HVAC contract renewed. Motion passed unanimously.",
    )

    # Exact byte-identical duplicate pair (same SHA-256).
    dup_a = root / "Bulletins" / "20190421_bulletin.pdf"
    dup_b = root / "Bulletins" / "20190421_bulletin_copy.pdf"
    shutil.copyfile(dup_a, dup_b)

    _write_zero_byte(root)
    _write_corrupt_pdf(root / "Scans")
    _write_password_protected_pdf(root / "Scans")
    _write_low_contrast_jpeg(root / "Scans")
    _write_high_contrast_jpeg(root / "Scans")
    _write_unicode_named_text(root)

    # A file that exclusion tests will mark as pastoral care.
    _write_text_pdf(
        root / "Pastoral Care",
        "counseling_notes_2019.pdf",
        "Counseling notes — confidential pastoral conversation.",
    )

    return root


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "archive.sqlite"
