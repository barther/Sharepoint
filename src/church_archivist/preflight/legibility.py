"""Legibility pre-check for scanned images and image-only PDFs.

Implements the spec's §6 criteria: Michelson contrast below 0.35 or estimated
effective DPI below 200 flags the file as messy/illegible for later high-res
routing. Runs fully local (no API), so feeding illegible scans to paid models
can be avoided.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# §6 thresholds
CONTRAST_MESSY_BELOW = 0.35
DPI_MESSY_BELOW = 200

# Below these, the page is effectively unreadable even by a human.
CONTRAST_ILLEGIBLE_BELOW = 0.15
DPI_ILLEGIBLE_BELOW = 100


@dataclass
class LegibilityResult:
    contrast: float | None
    estimated_dpi: int | None
    flag: str  # 'clean' | 'messy' | 'illegible' | 'not_applicable'


def assess(path: Path) -> LegibilityResult:
    ext = path.suffix.lower().lstrip(".")
    if ext in {"jpg", "jpeg", "png", "tif", "tiff", "gif", "bmp"}:
        return _assess_image(path)
    if ext == "pdf":
        return _assess_pdf_first_page(path)
    return LegibilityResult(None, None, "not_applicable")


def _michelson_contrast(gray) -> float:
    import numpy as np

    gmax = float(gray.max())
    gmin = float(gray.min())
    if gmax + gmin <= 0:
        return 0.0
    return (gmax - gmin) / (gmax + gmin)


def _estimate_dpi_from_pixels(pixel_width: int, pixel_height: int) -> int:
    """Very rough DPI estimate assuming standard US Letter (8.5" x 11").

    This is intentionally approximate — it's a triage signal, not a
    measurement. Real DPI may be embedded in the image metadata, but not all
    scanners record it honestly.
    """
    # Use the longer side against the longer paper dimension.
    longer = max(pixel_width, pixel_height)
    return int(longer / 11.0)


def _flag_from(contrast: float, dpi: int) -> str:
    if contrast < CONTRAST_ILLEGIBLE_BELOW or dpi < DPI_ILLEGIBLE_BELOW:
        return "illegible"
    if contrast < CONTRAST_MESSY_BELOW or dpi < DPI_MESSY_BELOW:
        return "messy"
    return "clean"


def _assess_image(path: Path) -> LegibilityResult:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return LegibilityResult(None, None, "not_applicable")

    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return LegibilityResult(None, None, "not_applicable")

    contrast = _michelson_contrast(img)
    h, w = img.shape[:2]
    dpi = _estimate_dpi_from_pixels(w, h)
    return LegibilityResult(
        contrast=round(contrast, 4),
        estimated_dpi=dpi,
        flag=_flag_from(contrast, dpi),
    )


def _assess_pdf_first_page(path: Path) -> LegibilityResult:
    """Rasterise the first page via Pillow+pypdf if possible; otherwise skip.

    We avoid pulling in poppler/pdf2image as a required dep — their install
    footprint is heavy. Instead we rely on embedded images: if the first page
    has one big image, we use that as the legibility proxy.
    """
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:
        return LegibilityResult(None, None, "not_applicable")

    try:
        reader = PdfReader(str(path))
    except PdfReadError:
        return LegibilityResult(None, None, "not_applicable")
    if reader.is_encrypted:
        return LegibilityResult(None, None, "not_applicable")
    if not reader.pages:
        return LegibilityResult(None, None, "not_applicable")

    first_page = reader.pages[0]
    try:
        images = list(first_page.images)
    except Exception:  # noqa: BLE001
        images = []

    if not images:
        # Text-layer PDF. Not applicable.
        return LegibilityResult(None, None, "not_applicable")

    # Pick the largest embedded image; that's typically the page scan.
    try:
        from PIL import Image
        import io
        import numpy as np
        import cv2
    except ImportError:
        return LegibilityResult(None, None, "not_applicable")

    best = max(images, key=lambda im: len(im.data))
    try:
        img = Image.open(io.BytesIO(best.data)).convert("L")
    except Exception:  # noqa: BLE001
        return LegibilityResult(None, None, "not_applicable")

    arr = np.array(img)
    if arr.size == 0:
        return LegibilityResult(None, None, "not_applicable")

    contrast = _michelson_contrast(arr)
    h, w = arr.shape[:2]
    dpi = _estimate_dpi_from_pixels(w, h)
    return LegibilityResult(
        contrast=round(contrast, 4),
        estimated_dpi=dpi,
        flag=_flag_from(contrast, dpi),
    )
