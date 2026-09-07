from __future__ import annotations

import re

from questbank.types.layout import BoundingBox, PageLayout, PaperLayout, TableRegion
from questbank.types.question import ParsedTable, TableRole


def coerce_question_number(raw: object) -> int:
    """Accept 1, \"1\", \"Q1\", etc."""
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    match = re.search(r"\d+", text)
    if not match:
        raise ValueError(f"Invalid question_number: {raw!r}")
    return int(match.group())


def format_page_layout_context(page: PageLayout, *, max_chars: int = 3000) -> str:
    """Serialize Docling/PyMuPDF layout for one page as LLM prompt context.

    Table cell content is listed under Tables only — free-text lines that sit
    inside a table bbox are omitted so the model does not copy grids into stem/parts.
    """
    chunks: list[str] = [f"Page {page.page_number} extracted text (Docling/PyMuPDF):"]

    ordered_lines = sorted(
        page.lines,
        key=lambda line: (
            line.reading_order if line.reading_order is not None else 10_000,
            line.y0,
            line.x0,
        ),
    )
    for line in ordered_lines:
        text = line.text.strip()
        if not text:
            continue
        if _line_inside_table(line, page.tables):
            continue
        chunks.append(text)

    if page.tables:
        chunks.append("")
        chunks.append("Tables on this page (do not copy cells into stem/parts):")
        for index, table in enumerate(page.tables, start=1):
            chunks.append(_format_table(index, table))

    context = "\n".join(chunks).strip()
    if len(context) > max_chars:
        return context[: max_chars - 3] + "..."
    return context


def _line_inside_table(line, tables: list[TableRegion]) -> bool:
    cx = (line.x0 + line.x1) / 2
    cy = (line.y0 + line.y1) / 2
    return any(table.bbox.contains_point(cx, cy) for table in tables)


def box2d_to_layout_bbox(
    box_2d: list[int] | tuple[int, ...] | None,
    page_width: float,
    page_height: float,
) -> BoundingBox | None:
    """Convert normalized [ymin,xmin,ymax,xmax] (0-1000) to PDF layout coordinates."""
    if not box_2d or len(box_2d) != 4:
        return None
    ymin, xmin, ymax, xmax = [int(value) for value in box_2d]
    x0 = max(0.0, min(page_width, (xmin / 1000) * page_width))
    y0 = max(0.0, min(page_height, (ymin / 1000) * page_height))
    x1 = max(0.0, min(page_width, (xmax / 1000) * page_width))
    y1 = max(0.0, min(page_height, (ymax / 1000) * page_height))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)


def tables_for_bbox(
    layout: PaperLayout,
    *,
    page_number: int,
    bbox: BoundingBox | None,
    role: TableRole = "stem",
) -> list[ParsedTable]:
    """Attach Docling tables whose bbox overlaps a question region."""
    if bbox is None:
        return []

    parsed: list[ParsedTable] = []
    for page in layout.pages:
        if page.page_number != page_number:
            continue
        for table in page.tables:
            if not bbox.overlaps(table.bbox, padding=12.0):
                continue
            # Require meaningful overlap so neighbouring questions do not steal tables.
            overlap = bbox.intersection_area(table.bbox)
            table_area = max(table.bbox.area(), 1.0)
            if overlap / table_area < 0.35:
                continue
            parsed.append(
                ParsedTable(
                    role=role,
                    page=table.page,
                    bounding_box=table.bbox,
                    headers=list(table.headers),
                    rows=[list(row) for row in table.rows],
                )
            )
    return parsed


def images_for_bbox(layout: PaperLayout, *, page_number: int, bbox: BoundingBox | None):
    """Return Docling/PyMuPDF image regions overlapping a question bbox."""
    if bbox is None:
        return []
    images = []
    for page in layout.pages:
        if page.page_number != page_number:
            continue
        page_area = max(page.width * page.height, 1.0)
        for image in page.images:
            # Image centre must sit inside the question band.
            cx = (image.bbox.x0 + image.bbox.x1) / 2
            cy = (image.bbox.y0 + image.bbox.y1) / 2
            if not bbox.contains_point(cx, cy, padding=12.0):
                continue
            if image.bbox.area() / page_area > 0.45:
                continue
            if image.bbox.area() < 2_500.0:
                continue
            images.append(image)
    return images


def _format_table(index: int, table: TableRegion) -> str:
    lines = [f"Table {index}:"]
    if table.headers:
        lines.append("Headers: " + " | ".join(table.headers))
    for row in table.rows[:20]:
        lines.append("Row: " + " | ".join(cell.strip() for cell in row if cell.strip()))
    if len(table.rows) > 20:
        lines.append(f"... ({len(table.rows) - 20} more rows)")
    return "\n".join(lines)
