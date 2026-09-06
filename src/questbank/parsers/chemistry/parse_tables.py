from __future__ import annotations

import re

from questbank.parsers.chemistry.detect_question_boundaries import QuestionSlice
from questbank.types.layout import ImageRegion, PaperLayout, TableRegion, TextLine
from questbank.types.question import OPTION_LABELS, OptionLabel, ParsedOption, ParsedTable, TableRole

_FIGURE_OVERLAP = 0.30
_LINE_IN_FIGURE = 0.50
_STACKED_OPTIONS = re.compile(
    r"^A(?:\s*\|\s*|\s+)B(?:\s*\|\s*|\s+)C(?:\s*\|\s*|\s+)D$",
    re.I,
)
_LEADING_OPTION = re.compile(r"^([A-D])\s+(.+)$")


def tables_for_slice(
    item: QuestionSlice,
    layout: PaperLayout,
    images: list[ImageRegion],
) -> list[ParsedTable]:
    parsed: list[ParsedTable] = []
    for table in _tables_in_slice(item, layout):
        if _table_overlaps_image(table, images):
            continue
        role = _table_role(table)
        headers, rows = _normalize_table_matrix(table.headers, table.rows, role)
        parsed.append(
            ParsedTable(
                role=role,
                page=table.page,
                bounding_box=table.bbox,
                headers=headers,
                rows=rows,
            )
        )
    return parsed


def options_from_tables(tables: list[ParsedTable]) -> dict[OptionLabel, str] | None:
    """Prefer structured option-table rows when Docling/PyMuPDF recovered A-D grids."""
    best: dict[OptionLabel, str] = {}
    for table in tables:
        if table.role != "options":
            continue
        found: dict[OptionLabel, str] = {}
        for row in table.rows:
            label, text = option_row_parts(row)
            if label is None or not text:
                continue
            found[label] = text  # type: ignore[assignment]
        if len(found) > len(best):
            best = found
    return best or None


def merge_options_with_tables(
    options: dict[OptionLabel, ParsedOption],
    tables: list[ParsedTable],
) -> dict[OptionLabel, ParsedOption]:
    table_options = options_from_tables(tables)
    if not table_options:
        return options
    merged = dict(options)
    for label, text in table_options.items():
        current = merged.get(label)
        if current is None or current.text is None or not current.text.strip() or current.requires_visual:
            merged[label] = ParsedOption(label=label, text=text, requires_visual=False)
        elif _looks_duplicated(current.text):
            merged[label] = ParsedOption(label=label, text=text, requires_visual=False)
    return merged


def option_row_parts(row: list[str]) -> tuple[OptionLabel | None, str]:
    if not row:
        return None, ""
    first = (row[0] or "").strip()
    if first in OPTION_LABELS:
        rest = [_clean_cell(cell) for cell in row[1:] if _clean_cell(cell)]
        return first, " ".join(rest)  # type: ignore[return-value]
    for index, cell in enumerate(row):
        value = (cell or "").strip()
        if value in OPTION_LABELS:
            rest = [
                _clean_cell(other)
                for other_index, other in enumerate(row)
                if other_index != index and _clean_cell(other)
            ]
            return value, " ".join(rest)  # type: ignore[return-value]
        match = _LEADING_OPTION.match(value)
        if match:
            rest = [match.group(2)]
            rest.extend(
                _clean_cell(other)
                for other_index, other in enumerate(row)
                if other_index != index and _clean_cell(other)
            )
            return match.group(1), " ".join(rest)  # type: ignore[return-value]
    return None, ""


def line_is_table_text(line: TextLine, tables: list[ParsedTable]) -> bool:
    cx = (line.x0 + line.x1) / 2
    cy = (line.y0 + line.y1) / 2
    return any(
        table.page == line.page and table.bounding_box.contains_point(cx, cy)
        for table in tables
    )


def line_is_figure_text(line: TextLine, images: list[ImageRegion]) -> bool:
    for image in images:
        if image.page != line.page:
            continue
        overlap = line.bbox.intersection_area(image.bbox)
        if overlap <= 0:
            continue
        line_area = line.bbox.area()
        if line_area and overlap / line_area >= _LINE_IN_FIGURE:
            return True
    return False


def _tables_in_slice(item: QuestionSlice, layout: PaperLayout) -> list[TableRegion]:
    y_start = item.start.line.y0
    last_line = item.lines[-1]
    tables: list[TableRegion] = []
    for page in layout.pages:
        if page.page_number < item.page_start or page.page_number > item.page_end:
            continue
        for table in page.tables:
            if page.page_number == item.page_start and table.bbox.y1 < y_start - 8:
                continue
            if page.page_number == item.page_end and table.bbox.y0 > last_line.y1 + 40:
                continue
            tables.append(table)
    return tables


def _table_role(table: TableRegion) -> TableRole:
    labels = _option_labels_in_rows(table.rows)
    if len(labels) >= 2:
        return "options"
    first_col = [(row[0] if row else "").strip() for row in table.rows]
    for cell in first_col:
        compact = re.sub(r"\s+", " ", cell).strip()
        if _STACKED_OPTIONS.match(compact) or "A | B | C | D" in compact:
            return "options"
    return "stem"


def _split_option_row(row: list[str]) -> tuple[str | None, list[str]]:
    # Skip collapsed PyMuPDF-style option dumps; text options come from line parser.
    joined = " ".join(_clean_cell(cell) for cell in row)
    if _STACKED_OPTIONS.search(joined.replace("|", " ")) or "A | B | C | D" in joined:
        return None, []

    label, text = option_row_parts(row)
    if label is None:
        return None, []
    for index, cell in enumerate(row):
        value = (cell or "").strip()
        if value == label:
            cells = [_clean_cell(other) for other_index, other in enumerate(row) if other_index != index]
            return label, cells
        match = _LEADING_OPTION.match(value)
        if match and match.group(1) == label and "|" not in value:
            remainder = match.group(2).strip()
            others = [
                _clean_cell(other)
                for other_index, other in enumerate(row)
                if other_index != index
            ]
            if remainder:
                if len(others) >= 2:
                    others[1] = f"{remainder} {others[1]}".strip()
                elif others:
                    others[0] = f"{remainder} {others[0]}".strip()
                else:
                    others.append(remainder)
            return label, others
    return label, [text] if text else []


def _normalize_table_matrix(
    headers: list[str],
    rows: list[list[str]],
    role: TableRole,
) -> tuple[list[str], list[list[str]]]:
    clean_headers = [_clean_cell(cell) for cell in headers]
    clean_rows = [[_clean_cell(cell) for cell in row] for row in rows]

    if role != "options":
        while clean_headers and not clean_headers[-1]:
            clean_headers.pop()
        return clean_headers, clean_rows

    aligned_rows: list[list[str]] = []
    data_width = 0
    for row in clean_rows:
        label, cells = _split_option_row(row)
        if label is None:
            continue
        aligned_rows.append([label, *cells])
        data_width = max(data_width, len(cells))

    if not aligned_rows:
        # Keep original matrix (e.g. collapsed A|B|C|D preview) but preserve headers.
        return _headers_with_label_slot(clean_headers), clean_rows

    for row in aligned_rows:
        while len(row) < data_width + 1:
            row.append("")

    data_headers = _option_data_headers(clean_headers, data_width)
    return ["", *data_headers], aligned_rows


def _headers_with_label_slot(headers: list[str]) -> list[str]:
    if not headers:
        return [""]
    if headers[0] == "":
        return headers
    return ["", *headers]


def _option_data_headers(headers: list[str], data_width: int) -> list[str]:
    meaningful = [
        header
        for header in headers
        if header and header.lower() not in {"unnamed: 0", "unnamed:0"} and header not in OPTION_LABELS
    ]
    if len(meaningful) >= data_width:
        return meaningful[:data_width]
    padded = list(meaningful)
    while len(padded) < data_width:
        padded.append("")
    # Prefer real headers; drop only pure trailing empties beyond known labels.
    while padded and not padded[-1] and len(padded) > len(meaningful):
        padded.pop()
    while len(padded) < data_width:
        padded.append("")
    return padded[:data_width]


def _option_labels_in_rows(rows: list[list[str]]) -> set[str]:
    labels: set[str] = set()
    for row in rows:
        for cell in row:
            value = (cell or "").strip()
            if value in OPTION_LABELS:
                labels.add(value)
                break
            match = _LEADING_OPTION.match(value)
            if match:
                labels.add(match.group(1))
                break
    return labels


def _looks_duplicated(text: str) -> bool:
    parts = text.split()
    if len(parts) < 4:
        return False
    half = len(parts) // 2
    return parts[:half] == parts[half : 2 * half]


def _clean_cell(cell: object) -> str:
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
        if table_area and overlap / table_area >= _FIGURE_OVERLAP:
            return True
        if image_area and overlap / image_area >= _FIGURE_OVERLAP:
            return True
    return False
