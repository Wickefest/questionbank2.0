from __future__ import annotations

from questbank.parsers.chemistry.parse_tables import (
    merge_options_with_tables,
    options_from_tables,
    option_row_parts,
    tables_for_slice,
    _table_role,
)
from questbank.parsers.chemistry.detect_question_boundaries import QuestionSlice, QuestionStart
from questbank.types.canonical import TableOptionRow, TableOptions
from questbank.types.layout import BoundingBox, PaperLayout, PageLayout, TableRegion, TextLine
from questbank.types.question import ParsedOption, ParsedTable


def test_electronic_config_option_table_is_text_not_visual():
    table = ParsedTable(
        role="options",
        page=6,
        bounding_box=BoundingBox(x0=95, y0=116, x1=552, y1=197),
        headers=["", "atom of X electronic configuration", "atom of Y electronic configuration"],
        rows=[
            ["A", "2, 1", "2, 7"],
            ["B", "2, 2", "2, 7"],
            ["C", "2, 1", "2, 6"],
            ["D", "2, 2", "2, 6"],
        ],
    )
    assert _table_role(
        TableRegion(
            page=6,
            bbox=table.bounding_box,
            headers=table.headers,
            rows=table.rows,
            row_count=4,
            col_count=3,
        )
    ) == "options"
    label, text = option_row_parts(["A", "2, 1", "2, 7"])
    assert label == "A"
    assert text == "2, 1 | 2, 7"

    empty = {
        label: ParsedOption(label=label, text=None, requires_visual=True)
        for label in ("A", "B", "C", "D")
    }
    merged = merge_options_with_tables(empty, [table])
    assert all(not merged[label].requires_visual for label in ("A", "B", "C", "D"))
    assert merged["A"].text == "2, 1 | 2, 7"
    assert options_from_tables([table]) == {
        "A": "2, 1 | 2, 7",
        "B": "2, 2 | 2, 7",
        "C": "2, 1 | 2, 6",
        "D": "2, 2 | 2, 6",
    }


def test_canonical_table_options_preserve_all_cells():
    """Regression: Q22-style multi-column option rows must keep every cell."""
    options = TableOptions(
        columns=["gas X", "gas Y"],
        rows=[
            TableOptionRow(label="A", cells=["H2", "O2"]),
            TableOptionRow(label="B", cells=["CH4", "H2"]),
            TableOptionRow(label="C", cells=["C3H8", "H2"]),
            TableOptionRow(label="D", cells=["CO2", "C3H8"]),
        ],
    )
    assert options.mode == "table"
    assert options.rows[0].cells == ["H2", "O2"]
    assert all(len(row.cells) == 2 for row in options.rows)
    # Cells stay separate — never a single flattened "H2O2" cell
    assert options.rows[0].cells != ["H2O2"]
    assert " | ".join(options.rows[0].cells) == "H2 | O2"


def test_tables_for_slice_uses_next_question_band():
    start_line = TextLine(
        text="10 The elements X and Y form the compound X2Y.",
        page=6,
        bbox=BoundingBox(x0=40, y0=60, x1=400, y1=75),
        block_index=0,
        line_index=0,
    )
    next_line = TextLine(
        text="11 Which of the following compounds...",
        page=6,
        bbox=BoundingBox(x0=40, y0=220, x1=400, y1=235),
        block_index=1,
        line_index=1,
    )
    item = QuestionSlice(
        number=10,
        start=QuestionStart(number=10, line=start_line, stem_prefix="The", line_index=0),
        lines=[start_line],
        page_start=6,
        page_end=6,
    )
    page = PageLayout(
        page_number=6,
        width=595,
        height=842,
        lines=[start_line, next_line],
        tables=[
            TableRegion(
                page=6,
                bbox=BoundingBox(x0=95, y0=116, x1=552, y1=197),
                headers=["", "atom of X", "atom of Y"],
                rows=[
                    ["A", "2, 1", "2, 7"],
                    ["B", "2, 2", "2, 7"],
                    ["C", "2, 1", "2, 6"],
                    ["D", "2, 2", "2, 6"],
                ],
                row_count=4,
                col_count=3,
            )
        ],
        images=[],
    )
    layout = PaperLayout(pages=[page])
    tables = tables_for_slice(
        item,
        layout,
        [],
        y_end_exclusive=next_line.y0,
        page_end_exclusive=6,
    )
    assert len(tables) == 1
    assert tables[0].role == "options"
