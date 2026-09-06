from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from questbank.types.layout import BoundingBox, ImageRegion, PageLayout, PaperLayout, TableRegion, TextLine

logger = logging.getLogger(__name__)

_OPTION_LABELS = ("A", "B", "C", "D")
_QUESTION_START = re.compile(r"^(?:Q\s*)?([1-9]|[1-3]\d|40)(?:[\.\)]\s*|\s+)(\S.*)$", re.I)
_EMBEDDED_QUESTION = re.compile(
    r"\s+(?=((?:[1-9]|[1-3]\d|40)\s+(?:[A-Z][a-z]+|[A-Z]\s+[a-z])))"
)
_QUESTION_NUMBER_X0 = 77.2



# Elevated OCR render scales for scanned papers. Keep moderate to avoid OOM on
# multi-page A4 scans (3.0/5.0 + page images previously access-violated on Windows).
_OCR_IMAGE_SCALE = 2.0
_OCR_RAPID_SCALE = 4.0


def extract_docling_layout(pdf_path: str | Path, *, do_ocr: bool = False) -> PaperLayout:
    """Extract structured layout via Docling (reading order, tables, pictures).

    Bounding boxes are converted to top-left origin so existing MCQ geometry
    heuristics keep working. Falls through to the caller on import/runtime errors.

    When ``do_ocr`` is True (scan-heavy PDFs), RapidOCR runs with English settings
    at elevated render/OCR scale for clearer text.
    """
    _patch_docling_pipeline_hash()

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling_core.types.doc import PictureItem, TableItem, TextItem

    path = Path(pdf_path)
    pipeline = PdfPipelineOptions()
    pipeline.do_ocr = bool(do_ocr)
    if do_ocr:
        pipeline.images_scale = _OCR_IMAGE_SCALE
        pipeline.ocr_options = RapidOcrOptions(
            lang=["english"],
            force_full_page_ocr=True,
            scale=_OCR_RAPID_SCALE,
        )
    pipeline.generate_page_images = False
    pipeline.generate_picture_images = False
    pipeline.do_table_structure = True

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline)}
    )
    result = converter.convert(str(path))
    document = result.document

    page_sizes = _page_sizes(document)
    page_numbers = sorted(page_sizes) or [1]
    buckets: dict[int, dict[str, list]] = {
        number: {"lines": [], "images": [], "tables": []} for number in page_numbers
    }

    order = 0
    for item, _level in document.iterate_items():
        if isinstance(item, TextItem):
            for line in _text_lines(item, page_sizes, order):
                buckets.setdefault(line.page, {"lines": [], "images": [], "tables": []})
                buckets[line.page]["lines"].append(line)
                order = (line.reading_order or order) + 1
        elif isinstance(item, TableItem):
            table = _table_region(item, document, page_sizes, order)
            if table is None:
                continue
            buckets.setdefault(table.page, {"lines": [], "images": [], "tables": []})
            buckets[table.page]["tables"].append(table)
            order += 1
        elif isinstance(item, PictureItem):
            image = _picture_region(item, page_sizes, order)
            if image is None:
                continue
            buckets.setdefault(image.page, {"lines": [], "images": [], "tables": []})
            buckets[image.page]["images"].append(image)
            order += 1

    pages: list[PageLayout] = []
    for number in sorted(buckets):
        width, height = page_sizes.get(number, (595.32, 841.92))
        lines = buckets[number]["lines"]
        images = buckets[number]["images"]
        tables = [
            table
            for table in buckets[number]["tables"]
            if not _table_overlaps_image(table, images)
        ]
        pages.append(
            PageLayout(
                page_number=number,
                width=width,
                height=height,
                raw_text="\n".join(line.text for line in lines),
                used_ocr=bool(do_ocr),
                lines=lines,
                images=images,
                tables=tables,
            )
        )
    if not pages:
        raise RuntimeError("Docling returned no pages")
    return PaperLayout(pages=pages)


def _patch_docling_pipeline_hash() -> None:
    """Work around Docling 2.126 + pydantic serialize_as_any circular-ref crash."""
    try:
        import docling.document_converter as dc_mod
        import docling.utils.pipeline_cache as pipeline_cache
        from docling.datamodel.pipeline_options import PipelineOptions
    except Exception:  # noqa: BLE001
        return

    def _safe_hash(pipeline_options: PipelineOptions) -> str:
        payload = type(pipeline_options).__qualname__ + pipeline_options.model_dump_json()
        return hashlib.md5(payload.encode("utf-8"), usedforsecurity=False).hexdigest()

    pipeline_cache.create_pipeline_options_hash = _safe_hash
    dc_mod.create_pipeline_options_hash = _safe_hash


def _page_sizes(document) -> dict[int, tuple[float, float]]:
    sizes: dict[int, tuple[float, float]] = {}
    pages = getattr(document, "pages", None) or {}
    if isinstance(pages, dict):
        for key, page in pages.items():
            number = int(getattr(page, "page_no", key) or key)
            size = getattr(page, "size", None)
            width = float(getattr(size, "width", 595.32) or 595.32)
            height = float(getattr(size, "height", 841.92) or 841.92)
            sizes[number] = (width, height)
    return sizes


def _text_lines(item, page_sizes: dict[int, tuple[float, float]], order: int) -> list[TextLine]:
    prov = item.prov[0] if getattr(item, "prov", None) else None
    if prov is None:
        return []
    page = int(prov.page_no)
    _, height = page_sizes.get(page, (595.32, 841.92))
    bbox = _to_topleft(prov.bbox, height)
    text = (getattr(item, "text", None) or "").strip()
    if not text:
        return []

    chunks = _split_embedded_questions(text)
    lines: list[TextLine] = []
    span = max(bbox.height() / max(len(chunks), 1), 10.0)
    for index, piece in enumerate(chunks):
        y0 = bbox.y0 + index * span
        x0 = bbox.x0
        if _QUESTION_START.match(piece):
            x0 = min(x0, _QUESTION_NUMBER_X0)
        lines.append(
            TextLine(
                text=piece,
                page=page,
                bbox=BoundingBox(x0=x0, y0=y0, x1=max(bbox.x1, x0 + 40), y1=min(bbox.y1, y0 + span)),
                block_index=order + index,
                line_index=index,
                reading_order=order + index,
            )
        )
    return lines


def _split_embedded_questions(text: str) -> list[str]:
    pieces = [part.strip() for part in text.splitlines() if part.strip()] or [text]
    chunks: list[str] = []
    for piece in pieces:
        start = 0
        for match in _EMBEDDED_QUESTION.finditer(piece):
            left = piece[start : match.start()].strip()
            if left:
                chunks.append(left)
            start = match.start()
        right = piece[start:].strip()
        if right:
            chunks.append(right)
    return chunks or [text]


def _table_region(
    item,
    document,
    page_sizes: dict[int, tuple[float, float]],
    order: int,
) -> TableRegion | None:
    del order
    prov = item.prov[0] if getattr(item, "prov", None) else None
    if prov is None:
        return None
    page = int(prov.page_no)
    _, height = page_sizes.get(page, (595.32, 841.92))
    bbox = _to_topleft(prov.bbox, height)

    matrix = _table_matrix(item, document)
    if matrix is None or len(matrix) < 2:
        return None
    col_count = max((len(row) for row in matrix), default=0)
    if col_count < 2:
        return None
    nonempty = sum(1 for row in matrix for cell in row if cell)
    if nonempty < 3:
        return None

    return TableRegion(
        page=page,
        bbox=bbox,
        headers=matrix[0],
        rows=matrix[1:],
        row_count=len(matrix),
        col_count=col_count,
    )


def _table_matrix(item, document) -> list[list[str]] | None:
    try:
        dataframe = item.export_to_dataframe(doc=document)
    except Exception:  # noqa: BLE001
        return _table_matrix_from_data(item)

    headers = [_cell_text(value) for value in dataframe.columns.tolist()]
    rows = [[_cell_text(value) for value in row] for row in dataframe.fillna("").astype(str).values.tolist()]
    if any(header and not header.startswith("Unnamed") for header in headers):
        return [headers, *rows]
    return rows if rows else None


def _table_matrix_from_data(item) -> list[list[str]] | None:
    data = getattr(item, "data", None)
    grid = getattr(data, "grid", None) if data is not None else None
    if not grid:
        return None
    matrix: list[list[str]] = []
    for row in grid:
        matrix.append([_cell_text(getattr(cell, "text", cell)) for cell in row])
    return matrix


def _picture_region(item, page_sizes: dict[int, tuple[float, float]], order: int) -> ImageRegion | None:
    prov = item.prov[0] if getattr(item, "prov", None) else None
    if prov is None:
        return None
    page = int(prov.page_no)
    _, height = page_sizes.get(page, (595.32, 841.92))
    return ImageRegion(page=page, bbox=_to_topleft(prov.bbox, height), block_index=order)


def _to_topleft(bbox, page_height: float) -> BoundingBox:
    left = float(getattr(bbox, "l", getattr(bbox, "x0", 0.0)))
    right = float(getattr(bbox, "r", getattr(bbox, "x1", 0.0)))
    top = float(getattr(bbox, "t", getattr(bbox, "y1", 0.0)))
    bottom = float(getattr(bbox, "b", getattr(bbox, "y0", 0.0)))
    origin = str(getattr(bbox, "coord_origin", "BOTTOMLEFT"))
    if "BOTTOM" in origin.upper():
        y0 = page_height - top
        y1 = page_height - bottom
    else:
        y0 = min(top, bottom)
        y1 = max(top, bottom)
    return BoundingBox(x0=min(left, right), y0=min(y0, y1), x1=max(left, right), y1=max(y0, y1))


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
