from __future__ import annotations

from questbank.parsers.chemistry.detect_structured_boundaries import detect_structured_boundaries
from questbank.parsers.chemistry.parse_structured_paper import parse_structured_paper
from questbank.types.layout import BoundingBox, TextLine
from tests.conftest import line, paper_from_lines


def test_detect_structured_q_boundaries_stops_before_answers():
    layout = paper_from_lines(
        [
            line("O Level Pure Chemistry Structured", x0=100, y0=40),
            line("Q1 (a) Ammonia is manufactured by the Haber Process.", x0=72, y0=80),
            line("(i) Describe the yield change.", x0=90, y0=120),
            line("Q2 Ammonia is prepared industrially.", x0=72, y0=200),
            line("(a) Read the graph.", x0=90, y0=240),
            line("Answers", x0=72, y0=400),
            line("Q1", x0=72, y0=430),
            line("Q2", x0=72, y0=460),
        ]
    )
    slices = detect_structured_boundaries(layout)
    assert [item.number for item in slices] == [1, 2]
    assert "Haber" in slices[0].start.stem_prefix or any(
        "Haber" in ln.text for ln in slices[0].lines
    )


def test_parse_structured_nests_roman_parts():
    layout = paper_from_lines(
        [
            line("Q1 Ammonia is manufactured by the Haber Process.", x0=72, y0=80),
            line("The table below shows yields.", x0=90, y0=100),
            line("(a) Use the table.", x0=90, y0=140),
            line("(i) Describe how yield changes with temperature. [1]", x0=100, y0=170),
            line("(ii) Describe how yield changes with pressure. [1]", x0=100, y0=200),
            line("(b) Explain the catalyst advantage. [2]", x0=90, y0=240),
            line("[Total: 4]", x0=480, y0=280),
        ]
    )
    paper = parse_structured_paper(
        "unused.pdf",
        layout=layout,
        ocr=False,
        extract_visuals=False,
        expected_count=1,
    )
    assert paper.validation.questions_detected == 1
    q1 = paper.questions[0]
    assert "Haber Process" in q1.stem
    assert "table below" in q1.stem
    assert len(q1.parts) == 2
    assert q1.parts[0].label == "a"
    assert [child.label for child in q1.parts[0].children] == ["i", "ii"]
    assert q1.parts[0].children[0].marks == 1
    assert q1.parts[1].label == "b"
    assert q1.parts[1].marks == 2
    assert q1.marks_total == 4
