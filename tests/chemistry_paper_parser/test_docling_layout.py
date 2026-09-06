from __future__ import annotations

from questbank.pdf.extract_docling_layout import _split_embedded_questions, _to_topleft
from questbank.parsers.chemistry.parse_tables import option_row_parts
from questbank.types.layout import BoundingBox, TableRegion
from questbank.parsers.chemistry.parse_tables import _table_role


class _FakeBBox:
    def __init__(self, l, t, r, b, coord_origin="BOTTOMLEFT"):
        self.l = l
        self.t = t
        self.r = r
        self.b = b
        self.coord_origin = coord_origin


def test_docling_bbox_bottomleft_to_topleft():
    bbox = _to_topleft(_FakeBBox(10, 800, 100, 780), page_height=842)
    assert bbox.x0 == 10
    assert bbox.x1 == 100
    assert abs(bbox.y0 - (842 - 800)) < 0.01
    assert abs(bbox.y1 - (842 - 780)) < 0.01


def test_split_embedded_question_40_from_option_line():
    text = "A 1, 2 and 3 B 1 and 2 only C 1 and 3 only D 2 and 3 only 40 A section of a polymer is shown below."
    chunks = _split_embedded_questions(text)
    assert len(chunks) == 2
    assert chunks[0].startswith("A 1, 2 and 3")
    assert chunks[1].startswith("40 A section")


def test_option_table_role_with_misplaced_labels():
    table = TableRegion(
        page=2,
        bbox=BoundingBox(x0=95, y0=300, x1=550, y1=450),
        headers=["", "section", "description"],
        rows=[
            ["P to Q", "The particles are stationary", "A"],
            ["Q to R", "bonds break", "B"],
            ["R to S", "particles expand", "C"],
            ["T to U", "water boils", "D"],
        ],
        row_count=5,
        col_count=3,
    )
    assert _table_role(table) == "options"
    label, text = option_row_parts(table.rows[0])
    assert label == "A"
    assert "P to Q" in text
