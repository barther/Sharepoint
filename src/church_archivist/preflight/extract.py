"""Text extraction from common document formats.

Tesseract is treated as optional per the spec: scans that have no extractable
text layer are flagged with `needs_ocr=True`; they do not fail the pipeline.

Files in formats we recognise but can't extract text from (Publisher,
Excel, PowerPoint, WordPerfect, etc.) are flagged with `unsupported_format`
so they don't silently masquerade as "processed" downstream. The category
label lets a later slice route them — convert via LibreOffice, send to
manual operator review, or quarantine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Minimum character count for a PDF/Word file to be considered "text-layer
# present" vs "looks like a scan we'd need OCR to read."  Empirically tuned
# low; a page of text is typically ~2000 chars, but a cover sheet or one-line
# memo can legitimately be under 100.
_MIN_TEXT_CHARS = 40


# Known-but-unhandled formats, grouped by category so downstream routing
# can act on the category rather than the raw extension. "publisher" is
# called out explicitly because Microsoft Publisher is EOL October 2026
# and these files will be converted to PDF separately; pre-flight just
# needs to surface their count so the conversion punch-list is visible.
_UNSUPPORTED_FORMATS: dict[str, str] = {
    "pub":   "publisher",
    "xls":   "spreadsheet",
    "xlsx":  "spreadsheet",
    "xlsm":  "spreadsheet",
    "ods":   "spreadsheet",
    "ppt":   "presentation",
    "pptx":  "presentation",
    "odp":   "presentation",
    "odt":   "wordprocessor",
    "wpd":   "wordperfect",
    "rtf":   "wordprocessor",
    "vsd":   "visio",
    "vsdx":  "visio",
    "pages": "iwork",
    "numbers": "iwork",
    "key":   "iwork",
    "msg":   "email",
    "pst":   "email",
    "ost":   "email",
    "eml":   "email",
    "mbox":  "email",
    "zip":   "archive",
    "7z":    "archive",
    "rar":   "archive",
    "tar":   "archive",
    "gz":    "archive",
    "mp3":   "audio",
    "wav":   "audio",
    "m4a":   "audio",
    "mp4":   "video",
    "mov":   "video",
    "avi":   "video",
    "accdb": "database",
    "mdb":   "database",
}


def _categorize_unsupported(ext: str) -> str:
    return _UNSUPPORTED_FORMATS.get(ext, "unrecognized")


@dataclass
class ExtractResult:
    extractable_text: bool
    char_count: int
    needs_ocr: bool
    is_encrypted: bool
    is_readable: bool
    failure_reason: str | None = None
    unsupported_format: str | None = None


def extract(path: Path) -> ExtractResult:
    ext = path.suffix.lower().lstrip(".")
    try:
        if ext == "pdf":
            return _extract_pdf(path)
        if ext == "docx":
            return _extract_docx(path)
        if ext == "doc":
            return _extract_doc_mammoth(path)
        if ext in {"txt", "md", "csv"}:
            return _extract_text(path)
        if ext in {"jpg", "jpeg", "png", "tif", "tiff", "gif", "bmp"}:
            return ExtractResult(
                extractable_text=False,
                char_count=0,
                needs_ocr=True,
                is_encrypted=False,
                is_readable=True,
            )
    except Exception as exc:  # noqa: BLE001 - we intentionally catch to flag
        return ExtractResult(
            extractable_text=False,
            char_count=0,
            needs_ocr=False,
            is_encrypted=False,
            is_readable=False,
            failure_reason=f"{type(exc).__name__}: {exc}",
        )

    # Unknown / known-but-unhandled extension: don't try to extract, but
    # don't fail either. Flag the category so downstream code can act.
    return ExtractResult(
        extractable_text=False,
        char_count=0,
        needs_ocr=False,
        is_encrypted=False,
        is_readable=True,
        unsupported_format=_categorize_unsupported(ext),
    )


def _extract_pdf(path: Path) -> ExtractResult:
    from pypdf import PdfReader
    from pypdf.errors import FileNotDecryptedError, PdfReadError

    try:
        reader = PdfReader(str(path))
    except PdfReadError as exc:
        return ExtractResult(False, 0, False, False, False, f"PdfReadError: {exc}")

    if reader.is_encrypted:
        # Try empty-password unlock (common for "soft" encryption).
        try:
            if reader.decrypt("") == 0:
                return ExtractResult(
                    extractable_text=False,
                    char_count=0,
                    needs_ocr=False,
                    is_encrypted=True,
                    is_readable=False,
                    failure_reason="password-protected",
                )
        except (FileNotDecryptedError, NotImplementedError):
            return ExtractResult(
                extractable_text=False,
                char_count=0,
                needs_ocr=False,
                is_encrypted=True,
                is_readable=False,
                failure_reason="password-protected",
            )

    chars = 0
    try:
        for page in reader.pages:
            text = page.extract_text() or ""
            chars += len(text)
    except Exception as exc:  # noqa: BLE001
        return ExtractResult(False, 0, False, False, False, f"page-extract: {exc}")

    extractable = chars >= _MIN_TEXT_CHARS
    needs_ocr = not extractable  # PDF with no/little text is likely a scan
    return ExtractResult(
        extractable_text=extractable,
        char_count=chars,
        needs_ocr=needs_ocr,
        is_encrypted=False,
        is_readable=True,
    )


def _extract_docx(path: Path) -> ExtractResult:
    from docx import Document

    doc = Document(str(path))
    chars = sum(len(p.text) for p in doc.paragraphs)
    return ExtractResult(
        extractable_text=chars >= _MIN_TEXT_CHARS,
        char_count=chars,
        needs_ocr=False,
        is_encrypted=False,
        is_readable=True,
    )


def _extract_doc_mammoth(path: Path) -> ExtractResult:
    # Legacy .doc isn't well supported by mammoth (which targets .docx).
    # We try, and if it fails we degrade gracefully without failing the run.
    import mammoth

    try:
        with path.open("rb") as fh:
            result = mammoth.extract_raw_text(fh)
        text = result.value or ""
        chars = len(text)
        return ExtractResult(
            extractable_text=chars >= _MIN_TEXT_CHARS,
            char_count=chars,
            needs_ocr=False,
            is_encrypted=False,
            is_readable=True,
        )
    except Exception as exc:  # noqa: BLE001
        return ExtractResult(
            extractable_text=False,
            char_count=0,
            needs_ocr=False,
            is_encrypted=False,
            is_readable=False,
            failure_reason=f"mammoth: {exc}",
        )


def _extract_text(path: Path) -> ExtractResult:
    try:
        data = path.read_bytes()
        text = data.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return ExtractResult(False, 0, False, False, False, str(exc))
    chars = len(text)
    return ExtractResult(
        extractable_text=chars >= _MIN_TEXT_CHARS,
        char_count=chars,
        needs_ocr=False,
        is_encrypted=False,
        is_readable=True,
    )
