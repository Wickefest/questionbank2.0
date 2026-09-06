from __future__ import annotations

from questbank.pdf.extract_pdf_layout import _merge_native_question_labels
from questbank.types.layout import BoundingBox, PageLayout, PaperLayout, TextLine
from pathlib import Path


def test_merge_native_question_labels_adds_missing_q_markers(tmp_path: Path):
    import pymupdf

    pdf_path = tmp_path / "labels.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((40, 100), "Q2")
    page.insert_text((40, 200), "Q3")
    doc.save(pdf_path)
    doc.close()

    layout = PaperLayout(
        pages=[
            PageLayout(
                page_number=1,
                width=595,
                height=842,
                lines=[
                    TextLine(
                        text="OCR body text only",
                        page=1,
                        bbox=BoundingBox(x0=80, y0=120, x1=400, y1=140),
                        block_index=0,
                        line_index=0,
                        reading_order=0,
                    )
                ],
            )
        ]
    )
    merged = _merge_native_question_labels(pdf_path, layout)
    labels = [line.text.upper().replace(" ", "") for line in merged.pages[0].lines]
    assert "Q2" in labels
    assert "Q3" in labels
