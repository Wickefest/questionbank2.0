from __future__ import annotations

from pathlib import Path

import pymupdf

from questbank.parsers.chemistry.parse_mcq_paper import parse_chemistry_paper_1


def test_pdf_page_break_does_not_split_question(tmp_path: Path):
    pdf = tmp_path / "page-break.pdf"
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    doc.new_page(width=595, height=842)
    page1 = doc[0]
    page2 = doc[1]
    page1.insert_text((77, 700), "1 A 15 cm3 sample of a gaseous hydrocarbon is burnt.")
    page1.insert_text((101, 720), "The total volume of the products is 75 cm3.")
    page2.insert_text((101, 80), "Which equation is correct?")
    page2.insert_text((101, 120), "A")
    page2.insert_text((129, 120), "CH4 (g) + 2O2 (g) -> CO2 (g) + 2H2O (g)")
    page2.insert_text((101, 140), "B")
    page2.insert_text((129, 140), "C2H4 (g) + 3O2 (g) -> 2CO2 (g) + 2H2O (g)")
    page2.insert_text((101, 160), "C")
    page2.insert_text((129, 160), "C3H8 (g) + 5O2 (g) -> 3CO2 (g) + 4H2O (g)")
    page2.insert_text((101, 180), "D")
    page2.insert_text((129, 180), "2C2H6 (g) + 7O2 (g) -> 4CO2 (g) + 6H2O (g)")
    page2.insert_text((77, 240), "2 Which salt is prepared differently?")
    page2.insert_text((101, 270), "A")
    page2.insert_text((129, 270), "ammonium nitrate")
    page2.insert_text((101, 290), "B")
    page2.insert_text((129, 290), "beryllium chloride")
    page2.insert_text((101, 310), "C")
    page2.insert_text((129, 310), "copper(II) sulfate")
    page2.insert_text((101, 330), "D")
    page2.insert_text((129, 330), "zinc sulfate")
    doc.save(pdf)
    doc.close()

    paper = parse_chemistry_paper_1(pdf, expected_count=2, backend="pymupdf")
    assert [q.question_number for q in paper.questions] == [1, 2]
    assert paper.questions[0].source.page_start == 1
    assert paper.questions[0].source.page_end == 2
    assert "75 cm3" in paper.questions[0].stem or "75 cm" in paper.questions[0].stem
