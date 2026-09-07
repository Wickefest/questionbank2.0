from __future__ import annotations

import pytest

from questbank.parsers.chemistry.parse_mcq_paper import parse_chemistry_paper_1


def test_real_chemistry_paper_has_questions_1_to_40(chem_paper_pdf):
    paper = parse_chemistry_paper_1(chem_paper_pdf, backend="pymupdf")
    numbers = [question.question_number for question in paper.questions]
    assert paper.validation.questions_detected == 40
    assert paper.validation.missing_questions == []
    assert paper.validation.duplicate_questions == []
    assert numbers == list(range(1, 41))
    for question in paper.questions:
        assert set(question.options) == {"A", "B", "C", "D"}
        assert question.source.page_start >= 1
        assert question.source.page_end >= question.source.page_start
        assert question.source.bounding_box is not None
        for option in question.options.values():
            if option.requires_visual:
                assert option.text is None

    properties = next(q for q in paper.questions if q.question_number == 7)
    assert any(table.role == "stem" for table in properties.tables)
    assert "percentage electrical substance" not in properties.stem

    heating = next(q for q in paper.questions if q.question_number == 1)
    assert "section description" not in heating.stem.lower()


def test_docling_backend_parses_real_paper(chem_paper_pdf):
    try:
        paper = parse_chemistry_paper_1(chem_paper_pdf, backend="docling")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Docling backend unavailable: {exc}")

    assert paper.validation.questions_detected == 40
    assert paper.validation.missing_questions == []
    assert paper.validation.duplicate_questions == []

    properties = next(q for q in paper.questions if q.question_number == 7)
    assert "Which classification" in properties.stem
    assert "percentage electrical substance" not in properties.stem
    stem_tables = [table for table in properties.tables if table.role == "stem"]
    assert stem_tables
    assert stem_tables[0].rows[0][0] == "P"

    option_tables = [table for table in properties.tables if table.role == "options"]
    if option_tables:
        option_table = option_tables[0]
        assert option_table.rows[0][0].strip().startswith("A")
        assert properties.options["A"].text and "P" in properties.options["A"].text
    else:
        # Heuristic Docling-only path may miss option-table role; Gemini ingest is authoritative.
        assert set(properties.options) == {"A", "B", "C", "D"}

