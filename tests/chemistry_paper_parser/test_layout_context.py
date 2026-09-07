from __future__ import annotations

from questbank.pdf.layout_context import (
    box2d_to_layout_bbox,
    format_page_layout_context,
    tables_for_bbox,
)
from questbank.types.layout import BoundingBox, PageLayout, PaperLayout, TableRegion, TextLine


def _line(text: str, y0: float) -> TextLine:
    return TextLine(
        text=text,
        page=1,
        bbox=BoundingBox(x0=72.0, y0=y0, x1=500.0, y1=y0 + 12.0),
        block_index=0,
        line_index=int(y0),
    )


def test_format_page_layout_context_includes_lines_and_tables():
    page = PageLayout(
        page_number=1,
        width=595.0,
        height=842.0,
        lines=[_line("1 Which element", 100.0), _line("A sodium", 140.0)],
        tables=[
            TableRegion(
                page=1,
                bbox=BoundingBox(x0=80.0, y0=200.0, x1=400.0, y1=280.0),
                headers=["P", "Q"],
                rows=[["1", "2"], ["3", "4"]],
                row_count=2,
                col_count=2,
            )
        ],
    )
    context = format_page_layout_context(page)
    assert "Which element" in context
    assert "Tables on this page" in context
    assert "do not copy cells" in context
    assert "Headers: P | Q" in context


def test_format_page_layout_context_skips_lines_inside_tables():
    table_bbox = BoundingBox(x0=80.0, y0=200.0, x1=400.0, y1=280.0)
    page = PageLayout(
        page_number=1,
        width=595.0,
        height=842.0,
        lines=[
            _line("1 Which element", 100.0),
            TextLine(
                text="P Q R",
                page=1,
                bbox=BoundingBox(x0=100.0, y0=220.0, x1=300.0, y1=232.0),
                block_index=1,
                line_index=1,
            ),
        ],
        tables=[
            TableRegion(
                page=1,
                bbox=table_bbox,
                headers=["P", "Q"],
                rows=[["1", "2"]],
                row_count=1,
                col_count=2,
            )
        ],
    )
    context = format_page_layout_context(page)
    assert "Which element" in context
    assert "P Q R" not in context
    assert "Headers: P | Q" in context


def test_box2d_to_layout_bbox_converts_normalized_coords():
    bbox = box2d_to_layout_bbox([100, 200, 500, 800], page_width=1000.0, page_height=2000.0)
    assert bbox == BoundingBox(x0=200.0, y0=200.0, x1=800.0, y1=1000.0)


def test_tables_for_bbox_returns_overlapping_tables():
    layout = PaperLayout(
        pages=[
            PageLayout(
                page_number=1,
                width=595.0,
                height=842.0,
                tables=[
                    TableRegion(
                        page=1,
                        bbox=BoundingBox(x0=80.0, y0=200.0, x1=400.0, y1=280.0),
                        headers=["A"],
                        rows=[["B"]],
                        row_count=1,
                        col_count=1,
                    )
                ],
            )
        ]
    )
    bbox = BoundingBox(x0=70.0, y0=190.0, x1=420.0, y1=300.0)
    tables = tables_for_bbox(layout, page_number=1, bbox=bbox, role="stem")
    assert len(tables) == 1
    assert tables[0].rows[0][0] == "B"
