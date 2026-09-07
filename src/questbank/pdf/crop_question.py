from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from questbank.types.layout import BoundingBox, PaperLayout, TextLine

_DEFAULT_DPI = 180
_SIDE_INSET = 36.0
_TOP_PAD = 6.0
_BOTTOM_PAD = 16.0


@dataclass(frozen=True)
class PageStrip:
    """One page region (PDF point space) belonging to a question slice."""

    page: int
    bbox: BoundingBox


def page_strips_from_lines(
    lines: list[TextLine],
    layout: PaperLayout,
    *,
    page_start: int,
    page_end: int,
) -> list[PageStrip]:
    """Build PDF-space crops covering the lines of one question slice."""
    by_page: dict[int, list[TextLine]] = {}
    for line in lines:
        if page_start <= line.page <= page_end:
            by_page.setdefault(line.page, []).append(line)

    page_sizes = {page.page_number: (page.width, page.height) for page in layout.pages}
    strips: list[PageStrip] = []
    for page_number in range(page_start, page_end + 1):
        page_lines = by_page.get(page_number) or []
        if not page_lines:
            continue
        width, height = page_sizes.get(page_number, (595.0, 842.0))
        y0 = max(0.0, min(line.y0 for line in page_lines) - _TOP_PAD)
        y1 = min(height, max(line.y1 for line in page_lines) + _BOTTOM_PAD)
        x0 = max(0.0, min(_SIDE_INSET, min(line.x0 for line in page_lines) - 8.0))
        x1 = min(width, max(width - _SIDE_INSET, max(line.x1 for line in page_lines) + 8.0))
        if y1 - y0 < 8 or x1 - x0 < 8:
            continue
        strips.append(
            PageStrip(
                page=page_number,
                bbox=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1),
            )
        )
    return strips


def union_strip_bbox(strips: list[PageStrip], *, page: int | None = None) -> BoundingBox | None:
    """Union of strip bboxes, optionally limited to one page (for source metadata)."""
    selected = [strip for strip in strips if page is None or strip.page == page]
    if not selected:
        return None
    merged = selected[0].bbox
    for strip in selected[1:]:
        merged = merged.union(strip.bbox)
    return merged


def render_strips_image(
    pdf_path: str | Path,
    strips: list[PageStrip],
    *,
    dpi: int = _DEFAULT_DPI,
):
    """Render page strips and stack them vertically into one RGB PIL image."""
    try:
        import pymupdf
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF and Pillow are required for question crops") from exc

    if not strips:
        raise ValueError("Cannot render an empty strip list")

    pdf_path = Path(pdf_path)
    pieces = []
    with pymupdf.open(pdf_path) as doc:
        for strip in strips:
            page_index = strip.page - 1
            if page_index < 0 or page_index >= doc.page_count:
                continue
            page = doc[page_index]
            clip = pymupdf.Rect(
                strip.bbox.x0,
                strip.bbox.y0,
                strip.bbox.x1,
                strip.bbox.y1,
            )
            pix = page.get_pixmap(dpi=dpi, alpha=False, clip=clip)
            pieces.append(Image.open(BytesIO(pix.tobytes("png"))).convert("RGB"))

    if not pieces:
        raise ValueError(f"No page strips could be rendered from {pdf_path}")
    if len(pieces) == 1:
        return pieces[0]

    width = max(image.width for image in pieces)
    height = sum(image.height for image in pieces)
    stacked = Image.new("RGB", (width, height), color=(255, 255, 255))
    y = 0
    for image in pieces:
        stacked.paste(image, (0, y))
        y += image.height
    return stacked


def format_slice_text_context(
    lines: list[TextLine],
    *,
    max_chars: int = 3000,
) -> str:
    """OCR/layout hint for one question slice (tables listed separately by callers)."""
    chunks: list[str] = []
    ordered = sorted(
        lines,
        key=lambda line: (
            line.page,
            line.reading_order if line.reading_order is not None else 10_000,
            line.y0,
            line.x0,
        ),
    )
    for line in ordered:
        text = line.text.strip()
        if text:
            chunks.append(text)
    context = "\n".join(chunks).strip()
    if len(context) > max_chars:
        return context[: max_chars - 3] + "..."
    return context
