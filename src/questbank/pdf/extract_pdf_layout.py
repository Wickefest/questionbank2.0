from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from questbank.types.layout import BoundingBox, ImageRegion, PageLayout, PaperLayout, TableRegion, TextLine

logger = logging.getLogger(__name__)

LayoutBackend = Literal["auto", "docling", "pymupdf"]

_MIN_NATIVE_CHARS = 20
_SPARSE_NATIVE_CHARS = 80


def extract_pdf_layout(
    pdf_path: str | Path,
    backend: LayoutBackend = "auto",
    *,
    ocr: bool | None = None,
) -> PaperLayout:
    """Extract page layout for parsing.

    ``docling`` (default via ``auto``) provides reading order, tables, and pictures.
    ``pymupdf`` remains available as a fast fallback and for tests.

    ``ocr``:
      - ``True`` — force Docling RapidOCR
      - ``False`` — never OCR via Docling
      - ``None`` — auto: OCR when native PDF text is sparse (scanned papers)
    """
    path = Path(pdf_path)
    use_ocr = bool(ocr) if ocr is not None else _native_text_is_sparse(path)
    if backend in ("auto", "docling"):
        try:
            from questbank.pdf.extract_docling_layout import extract_docling_layout

            layout = extract_docling_layout(path, do_ocr=use_ocr)
            if use_ocr:
                layout = _merge_native_question_labels(path, layout)
            logger.info(
                "Using Docling layout backend for %s (ocr=%s)",
                path.name,
                use_ocr,
            )
            return layout
        except Exception as exc:  # noqa: BLE001
            if backend == "docling":
                raise RuntimeError(f"Docling layout extraction failed: {exc}") from exc
            logger.warning("Docling unavailable (%s); falling back to PyMuPDF", exc)

    return extract_pymupdf_layout(path)


def _native_text_is_sparse(pdf_path: Path) -> bool:
    """True when the PDF has almost no selectable text (likely page scans)."""
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        return False
    try:
        with pymupdf.open(pdf_path) as doc:
            sample_pages = min(3, doc.page_count)
            total = 0
            for index in range(sample_pages):
                total += len((doc[index].get_text("text") or "").strip())
            return total < _SPARSE_NATIVE_CHARS
    except Exception:  # noqa: BLE001
        return False


def _merge_native_question_labels(pdf_path: Path, layout: PaperLayout) -> PaperLayout:
    """Inject native selectable Q# labels that OCR often misses on scan PDFs."""
    import re

    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        return layout

    label_re = re.compile(r"^Q\s*\d{1,2}$", re.I)
    native_labels: list[TextLine] = []
    with pymupdf.open(pdf_path) as doc:
        for page_index, page in enumerate(doc):
            page_number = page_index + 1
            data = page.get_text("dict") or {}
            for block_index, block in enumerate(data.get("blocks", [])):
                if block.get("type") != 0:
                    continue
                for line_index, raw_line in enumerate(block.get("lines", [])):
                    spans = raw_line.get("spans", [])
                    text = "".join(span.get("text", "") for span in spans).strip()
                    if not label_re.match(text):
                        continue
                    bbox = raw_line.get("bbox") or block.get("bbox") or [0, 0, 0, 0]
                    native_labels.append(
                        TextLine(
                            text=text.replace(" ", ""),
                            page=page_number,
                            bbox=BoundingBox(
                                x0=float(bbox[0]),
                                y0=float(bbox[1]),
                                x1=float(bbox[2]),
                                y1=float(bbox[3]),
                            ),
                            block_index=10_000 + block_index,
                            line_index=line_index,
                            reading_order=None,
                        )
                    )

    if not native_labels:
        return layout

    pages: list[PageLayout] = []
    for page in layout.pages:
        existing = {
            re.sub(r"\s+", "", line.text.strip().upper())
            for line in page.lines
            if label_re.match(line.text.strip())
        }
        extras = [
            label
            for label in native_labels
            if label.page == page.page_number
            and re.sub(r"\s+", "", label.text.strip().upper()) not in existing
        ]
        if not extras:
            pages.append(page)
            continue
        merged_lines = sorted(
            [*page.lines, *extras],
            key=lambda item: (item.y0, item.x0),
        )
        for order, line in enumerate(merged_lines):
            if line.reading_order is None:
                merged_lines[order] = line.model_copy(update={"reading_order": order})
        pages.append(
            page.model_copy(
                update={
                    "lines": merged_lines,
                    "raw_text": "\n".join(line.text for line in merged_lines),
                }
            )
        )
    return PaperLayout(pages=pages)


def extract_pymupdf_layout(pdf_path: str | Path) -> PaperLayout:
    """Extract native text lines, images, tables, and geometry with PyMuPDF."""
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF is required for PDF extraction") from exc

    path = Path(pdf_path)
    pages: list[PageLayout] = []
    with pymupdf.open(path) as doc:
        for index, page in enumerate(doc):
            pages.append(_extract_page(page, index + 1))
    return PaperLayout(pages=pages)


def _extract_page(page, page_number: int) -> PageLayout:
    width = float(page.rect.width)
    height = float(page.rect.height)
    native_text = page.get_text("text") or ""
    used_ocr = False

    if _native_text_unusable(native_text):
        ocr_text = _ocr_page_text(page)
        if ocr_text and len(ocr_text.strip()) > len(native_text.strip()):
            used_ocr = True
            images = _extract_images(page, page_number)
            return PageLayout(
                page_number=page_number,
                width=width,
                height=height,
                raw_text=ocr_text,
                used_ocr=True,
                lines=_lines_from_plain_text(ocr_text, page_number, width, height),
                images=images,
                tables=_extract_tables(page, page_number, images),
            )

    data = page.get_text("dict") or {}
    lines: list[TextLine] = []
    images: list[ImageRegion] = []
    for block_index, block in enumerate(data.get("blocks", [])):
        bbox = _bbox(block.get("bbox") or [0, 0, 0, 0])
        if block.get("type") != 0:
            images.append(ImageRegion(page=page_number, bbox=bbox, block_index=block_index))
            continue
        for line_index, line in enumerate(block.get("lines", [])):
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans).strip()
            if not text:
                continue
            sizes = [float(span.get("size") or 0) for span in spans]
            flags = 0
            for span in spans:
                flags |= int(span.get("flags") or 0)
            lines.append(
                TextLine(
                    text=text,
                    page=page_number,
                    bbox=_bbox(line.get("bbox") or block.get("bbox") or [0, 0, 0, 0]),
                    block_index=block_index,
                    line_index=line_index,
                    font_size=sum(sizes) / len(sizes) if sizes else 0.0,
                    flags=flags,
                )
            )

    if not images:
        images = _extract_images(page, page_number)

    return PageLayout(
        page_number=page_number,
        width=width,
        height=height,
        raw_text=native_text,
        used_ocr=used_ocr,
        lines=lines,
        images=images,
        tables=_extract_tables(page, page_number, images),
    )


def _extract_tables(page, page_number: int, images: list[ImageRegion]) -> list[TableRegion]:
    try:
        finder = page.find_tables()
        raw_tables = list(finder.tables) if finder else []
    except Exception:  # noqa: BLE001
        return []

    tables: list[TableRegion] = []
    for raw in raw_tables:
        region = _table_from_finder(raw, page_number)
        if region is None:
            continue
        if _table_overlaps_image(region, images):
            continue
        tables.append(region)
    return tables


def _table_from_finder(raw, page_number: int) -> TableRegion | None:
    try:
        extracted = raw.extract() or []
    except Exception:  # noqa: BLE001
        return None
    cleaned = [[_cell_text(cell) for cell in row] for row in extracted]
    if len(cleaned) < 2:
        return None
    col_count = max((len(row) for row in cleaned), default=0)
    if col_count < 2:
        return None
    nonempty = sum(1 for row in cleaned for cell in row if cell)
    if nonempty < 3:
        return None
    return TableRegion(
        page=page_number,
        bbox=_bbox(raw.bbox),
        headers=cleaned[0],
        rows=cleaned[1:],
        row_count=len(cleaned),
        col_count=col_count,
    )


def _cell_text(cell: object) -> str:
    if cell is None:
        return ""
    return " ".join(str(cell).replace("\n", " ").split())


def _table_overlaps_image(table: TableRegion, images: list[ImageRegion]) -> bool:
    table_area = table.bbox.area()
    for image in images:
        if image.page != table.page:
            continue
        overlap = table.bbox.intersection_area(image.bbox)
        if overlap <= 0:
            continue
        image_area = image.bbox.area()
        if table_area and overlap / table_area >= 0.30:
            return True
        if image_area and overlap / image_area >= 0.30:
            return True
    return False


def _extract_images(page, page_number: int) -> list[ImageRegion]:
    images: list[ImageRegion] = []
    try:
        raw_images = page.get_images(full=True)
    except Exception:  # noqa: BLE001
        return images
    for index, img in enumerate(raw_images):
        try:
            bbox = page.get_image_bbox(img)
        except Exception:  # noqa: BLE001
            continue
        images.append(
            ImageRegion(
                page=page_number,
                bbox=BoundingBox(
                    x0=float(bbox.x0),
                    y0=float(bbox.y0),
                    x1=float(bbox.x1),
                    y1=float(bbox.y1),
                ),
                block_index=index,
            )
        )
    return images


def _native_text_unusable(text: str) -> bool:
    stripped = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t").strip()
    return len(stripped) < _MIN_NATIVE_CHARS


def _ocr_page_text(page) -> str:
    try:
        textpage = page.get_textpage_ocr()
        return page.get_text("text", textpage=textpage) or ""
    except Exception:  # noqa: BLE001
        return ""


def _lines_from_plain_text(
    text: str, page_number: int, width: float, height: float
) -> list[TextLine]:
    lines: list[TextLine] = []
    usable = [line.strip() for line in text.splitlines() if line.strip()]
    if not usable:
        return lines
    row_height = height / max(len(usable) + 2, 1)
    for index, line in enumerate(usable):
        y0 = 40 + index * row_height
        lines.append(
            TextLine(
                text=line,
                page=page_number,
                bbox=BoundingBox(x0=72, y0=y0, x1=width - 40, y1=y0 + row_height),
                block_index=index,
                line_index=0,
            )
        )
    return lines


def _bbox(values: list[float] | tuple[float, ...]) -> BoundingBox:
    return BoundingBox(
        x0=float(values[0]),
        y0=float(values[1]),
        x1=float(values[2]),
        y1=float(values[3]),
    )
