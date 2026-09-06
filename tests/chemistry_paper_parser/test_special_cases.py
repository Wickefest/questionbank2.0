from __future__ import annotations

from questbank.parsers.chemistry.parse_mcq_paper import parse_chemistry_paper_1
from questbank.types.layout import BoundingBox, ImageRegion, TableRegion
from tests.conftest import line, paper_from_lines, qnum


def _parse(lines, images=None, tables=None, expected_count=1):
    return parse_chemistry_paper_1(
        "unused.pdf",
        expected_count=expected_count,
        layout=paper_from_lines(lines, images=images, tables=tables),
    )


def test_normal_text_mcq():
    paper = _parse(
        [
            qnum(1, y0=80, isolated=False, stem="Which metal is the most reactive?"),
            line("A", x0=101.3, y0=120),
            line("iron and calcium", x0=129, y0=120),
            line("B", x0=101.3, y0=140),
            line("zinc and copper", x0=129, y0=140),
            line("C", x0=101.3, y0=160),
            line("sodium only", x0=129, y0=160),
            line("D", x0=101.3, y0=180),
            line("gold only", x0=129, y0=180),
        ]
    )
    question = paper.questions[0]
    assert question.question_number == 1
    assert "most reactive" in question.stem
    assert question.options["A"].text == "iron and calcium"
    assert question.options["B"].text == "zinc and copper"
    assert question.options["C"].text == "sodium only"
    assert question.options["D"].text == "gold only"
    assert question.options["A"].requires_visual is False


def test_multiline_question_stem():
    paper = _parse(
        [
            qnum(1, y0=80),
            line("A student dissolves a salt in water.", x0=101.3, y0=82),
            line("The solution is then warmed gently.", x0=101.3, y0=98),
            line("Which observation is correct?", x0=101.3, y0=130),
            line("A", x0=101.3, y0=160),
            line("a white precipitate forms", x0=129, y0=160),
            line("B", x0=101.3, y0=180),
            line("no change is seen", x0=129, y0=180),
            line("C", x0=101.3, y0=200),
            line("a brown gas is evolved", x0=129, y0=200),
            line("D", x0=101.3, y0=220),
            line("the salt melts", x0=129, y0=220),
        ]
    )
    assert "dissolves a salt" in paper.questions[0].stem
    assert "warmed gently" in paper.questions[0].stem
    assert "Which observation is correct?" in paper.questions[0].stem


def test_multiline_answer_option():
    paper = _parse(
        [
            qnum(1, y0=80, isolated=False, stem="Which method is best?"),
            line("A", x0=101.3, y0=120),
            line("Add excess nitric acid to barium carbonate followed by dilute sulfuric acid and", x0=129, y0=120),
            line("filter.", x0=129, y0=136),
            line("B", x0=101.3, y0=160),
            line("Heat the carbonate only.", x0=129, y0=160),
            line("C", x0=101.3, y0=180),
            line("Filter then evaporate.", x0=129, y0=180),
            line("D", x0=101.3, y0=200),
            line("Use chromatography.", x0=129, y0=200),
        ]
    )
    assert "followed by dilute sulfuric acid" in (paper.questions[0].options["A"].text or "")
    assert "filter." in (paper.questions[0].options["A"].text or "")


def test_chemical_equation_in_question_and_option():
    paper = _parse(
        [
            qnum(1, y0=80, isolated=False, stem="Which equation is balanced?"),
            line("CH4 (g) + 2O2 (g) → CO2 (g) + 2H2O (g) is one possibility.", x0=101.3, y0=100),
            line("A", x0=101.3, y0=140),
            line("CH4 (g) + 2O2 (g) → CO2 (g) + 2H2O (g)", x0=129, y0=140),
            line("B", x0=101.3, y0=160),
            line("C2H4 (g) + 3O2 (g) → 2CO2 (g) + 2H2O (g)", x0=129, y0=160),
            line("C", x0=101.3, y0=180),
            line("C3H8 (g) + 5O2 (g) → 3CO2 (g) + 4H2O (g)", x0=129, y0=180),
            line("D", x0=101.3, y0=200),
            line("2C2H6 (g) + 7O2 (g) → 4CO2 (g) + 6H2O (g)", x0=129, y0=200),
        ]
    )
    stem = paper.questions[0].stem
    assert "CH4 (g) + 2O2 (g) → CO2 (g) + 2H2O (g)" in stem
    assert paper.questions[0].options["D"].text == "2C2H6 (g) + 7O2 (g) → 4CO2 (g) + 6H2O (g)"


def test_table_style_answer_options():
    paper = _parse(
        [
            qnum(1, y0=80, isolated=False, stem="Which row is correct?"),
            line("protons", x0=161, y0=110),
            line("neutrons", x0=269, y0=110),
            line("electrons", x0=381, y0=110),
            line("A", x0=101.3, y0=130),
            line("16", x0=174, y0=130),
            line("18", x0=286, y0=130),
            line("14", x0=398, y0=130),
            line("B", x0=101.3, y0=150),
            line("16", x0=174, y0=150),
            line("18", x0=286, y0=150),
            line("18", x0=398, y0=150),
            line("C", x0=101.3, y0=170),
            line("18", x0=174, y0=170),
            line("16", x0=286, y0=170),
            line("14", x0=398, y0=170),
            line("D", x0=101.3, y0=190),
            line("18", x0=174, y0=190),
            line("16", x0=286, y0=190),
            line("18", x0=398, y0=190),
        ]
    )
    assert paper.questions[0].options["A"].text == "16 18 14"
    assert paper.questions[0].options["B"].text == "16 18 18"


def test_graph_based_question_flags_visual_without_extracting_graph():
    paper = _parse(
        [
            qnum(1, y0=80),
            line("The following shows the heating curve of ice.", x0=101.3, y0=82),
            line("Which description in the table below best explains the graph?", x0=101.3, y0=200),
            line("A", x0=101.3, y0=240),
            line("P to Q particles are stationary", x0=129, y0=240),
            line("B", x0=101.3, y0=260),
            line("Q to R bonds break", x0=129, y0=260),
            line("C", x0=101.3, y0=280),
            line("R to S particles expand", x0=129, y0=280),
            line("D", x0=101.3, y0=300),
            line("T to U water boils", x0=129, y0=300),
        ],
        images=[
            ImageRegion(
                page=1,
                bbox=BoundingBox(x0=220, y0=100, x1=420, y1=190),
                block_index=20,
            )
        ],
    )
    question = paper.questions[0]
    assert question.visual.required is True
    assert question.visual.extraction_pending is True
    assert "heating curve" in question.stem


def test_apparatus_based_question_flags_visual():
    paper = _parse(
        [
            qnum(1, y0=80),
            line("The apparatus shown below consists of a porous pot.", x0=101.3, y0=82),
            line("Which pair of gases causes movement?", x0=101.3, y0=200),
            line("A", x0=101.3, y0=240),
            line("H2  O2", x0=129, y0=240),
            line("B", x0=101.3, y0=260),
            line("CH4  H2", x0=129, y0=260),
            line("C", x0=101.3, y0=280),
            line("C3H8  H2", x0=129, y0=280),
            line("D", x0=101.3, y0=300),
            line("CO2  C3H8", x0=129, y0=300),
        ]
    )
    assert paper.questions[0].visual.required is True
    assert "H2" in (paper.questions[0].options["A"].text or "")
    assert "O2" in (paper.questions[0].options["A"].text or "")


def test_visual_answer_choices_have_null_text():
    paper = _parse(
        [
            qnum(1, y0=80, isolated=False, stem="Which method should he use to collect dry ammonia?"),
            line("A", x0=101.3, y0=200),
            line("B", x0=329.2, y0=200),
            line("C", x0=101.3, y0=360),
            line("D", x0=329.2, y0=360),
        ],
        images=[
            ImageRegion(page=1, bbox=BoundingBox(x0=120, y0=200, x1=280, y1=330), block_index=8),
            ImageRegion(page=1, bbox=BoundingBox(x0=340, y0=200, x1=520, y1=330), block_index=9),
            ImageRegion(page=1, bbox=BoundingBox(x0=120, y0=360, x1=280, y1=490), block_index=10),
            ImageRegion(page=1, bbox=BoundingBox(x0=340, y0=360, x1=520, y1=490), block_index=11),
        ],
    )
    question = paper.questions[0]
    for label in ("A", "B", "C", "D"):
        assert question.options[label].text is None
        assert question.options[label].requires_visual is True
    assert any(
        issue.code == "VISUAL_OPTION_EXTRACTION_PENDING" for issue in question.validation.issues
    )


def test_multiple_questions_on_one_page():
    paper = _parse(
        [
            qnum(1, y0=80, isolated=False, stem="First question?"),
            line("A", x0=101.3, y0=110),
            line("one", x0=129, y0=110),
            line("B", x0=101.3, y0=130),
            line("two", x0=129, y0=130),
            line("C", x0=101.3, y0=150),
            line("three", x0=129, y0=150),
            line("D", x0=101.3, y0=170),
            line("four", x0=129, y0=170),
            qnum(2, y0=220, isolated=False, stem="Second question?"),
            line("A", x0=101.3, y0=250),
            line("red", x0=129, y0=250),
            line("B", x0=101.3, y0=270),
            line("blue", x0=129, y0=270),
            line("C", x0=101.3, y0=290),
            line("green", x0=129, y0=290),
            line("D", x0=101.3, y0=310),
            line("yellow", x0=129, y0=310),
        ],
        expected_count=2,
    )
    assert [q.question_number for q in paper.questions] == [1, 2]
    assert paper.questions[0].options["A"].text == "one"
    assert paper.questions[1].options["A"].text == "red"


def _tiny_question(number: int, y0: float) -> list:
    return [
        qnum(number, y0=y0, isolated=False, stem=f"Tiny stem {number}?"),
        line("A", x0=101.3, y0=y0 + 16),
        line("aa", x0=129, y0=y0 + 16),
        line("B", x0=101.3, y0=y0 + 32),
        line("bb", x0=129, y0=y0 + 32),
        line("C", x0=101.3, y0=y0 + 48),
        line("cc", x0=129, y0=y0 + 48),
        line("D", x0=101.3, y0=y0 + 64),
        line("dd", x0=129, y0=y0 + 64),
    ]


def test_q9_to_q10_does_not_use_embedded_ten():
    lines = []
    y0 = 60.0
    for number in range(1, 9):
        lines.extend(_tiny_question(number, y0))
        y0 += 80
    lines.extend(
        [
            qnum(9, y0=y0, isolated=False, stem="The isotopes include 23Na and 24Na."),
            line("A 10 cm3 sample is irrelevant here.", x0=101.3, y0=y0 + 16),
            line("A", x0=101.3, y0=y0 + 40),
            line("same density", x0=129, y0=y0 + 40),
            line("B", x0=101.3, y0=y0 + 56),
            line("different formula", x0=129, y0=y0 + 56),
            line("C", x0=101.3, y0=y0 + 72),
            line("different rate", x0=129, y0=y0 + 72),
            line("D", x0=101.3, y0=y0 + 88),
            line("same carbonate", x0=129, y0=y0 + 88),
            qnum(10, page=2, y0=80, isolated=False, stem="The elements X and Y form X2Y."),
            line("A", page=2, x0=101.3, y0=110),
            line("2, 1 and 2, 7", page=2, x0=129, y0=110),
            line("B", page=2, x0=101.3, y0=126),
            line("2, 2 and 2, 7", page=2, x0=129, y0=126),
            line("C", page=2, x0=101.3, y0=142),
            line("2, 1 and 2, 6", page=2, x0=129, y0=142),
            line("D", page=2, x0=101.3, y0=158),
            line("2, 2 and 2, 6", page=2, x0=129, y0=158),
            line("10", page=2, x0=174, y0=158),
        ]
    )
    paper = _parse(lines, expected_count=10)
    assert [q.question_number for q in paper.questions] == list(range(1, 11))
    assert "X2Y" in paper.questions[9].stem
    assert "10 cm3" in paper.questions[8].stem
    assert paper.questions[9].options["D"].text and "2, 2 and 2, 6" in paper.questions[9].options["D"].text


def test_page_transition_keeps_question_open():
    paper = _parse(
        [
            qnum(1, page=1, y0=700, isolated=False, stem="A 15 cm3 sample of hydrocarbon is burnt."),
            line("The total volume of the products is 75 cm3.", page=1, x0=101.3, y0=720),
            line("Which equation is correct?", page=2, x0=101.3, y0=80),
            line("A", page=2, x0=101.3, y0=120),
            line("CH4 (g) + 2O2 (g) → CO2 (g) + 2H2O (g)", page=2, x0=129, y0=120),
            line("B", page=2, x0=101.3, y0=140),
            line("C2H4 (g) + 3O2 (g) → 2CO2 (g) + 2H2O (g)", page=2, x0=129, y0=140),
            line("C", page=2, x0=101.3, y0=160),
            line("C3H8 (g) + 5O2 (g) → 3CO2 (g) + 4H2O (g)", page=2, x0=129, y0=160),
            line("D", page=2, x0=101.3, y0=180),
            line("2C2H6 (g) + 7O2 (g) → 4CO2 (g) + 6H2O (g)", page=2, x0=129, y0=180),
            qnum(2, page=2, y0=240, isolated=False, stem="Which salt is prepared differently?"),
            line("A", page=2, x0=101.3, y0=270),
            line("ammonium nitrate", page=2, x0=129, y0=270),
            line("B", page=2, x0=101.3, y0=290),
            line("beryllium chloride", page=2, x0=129, y0=290),
            line("C", page=2, x0=101.3, y0=310),
            line("copper(II) sulfate", page=2, x0=129, y0=310),
            line("D", page=2, x0=101.3, y0=330),
            line("zinc sulfate", page=2, x0=129, y0=330),
        ],
        expected_count=2,
    )
    first = paper.questions[0]
    assert first.source.page_start == 1
    assert first.source.page_end == 2
    assert "15 cm3" in first.stem
    assert "75 cm3" in first.stem
    assert first.options["A"].text.startswith("CH4")


def test_missing_option_does_not_invent_text():
    paper = _parse(
        [
            qnum(1, y0=80, isolated=False, stem="Which statement is true?"),
            line("A", x0=101.3, y0=120),
            line("iron", x0=129, y0=120),
            line("B", x0=101.3, y0=140),
            line("zinc", x0=129, y0=140),
            line("C", x0=101.3, y0=160),
            line("copper", x0=129, y0=160),
        ]
    )
    question = paper.questions[0]
    assert question.options["D"].text is None
    assert question.options["D"].requires_visual is False
    assert question.validation.status == "review"
    assert any(issue.code == "MISSING_OPTION_TEXT" for issue in question.validation.issues)


def test_apparatus_numbers_are_not_new_questions():
    paper = _parse(
        [
                qnum(1, y0=80, isolated=True),
                line("Which apparatus must she use?", x0=101.3, y0=82),
                line("1", x0=134.9, y0=160),
                line("2", x0=208.9, y0=160),
                line("3", x0=282.9, y0=160),
                line("4", x0=356.8, y0=160),
                line("A", x0=101.3, y0=300),
                line("1, 2, 3 and 4", x0=129, y0=300),
                line("B", x0=101.3, y0=320),
                line("1, 4 and 6", x0=129, y0=320),
                line("C", x0=101.3, y0=340),
                line("1, 5 and 6", x0=129, y0=340),
                line("D", x0=101.3, y0=360),
                line("2, 4, 5 and 6", x0=129, y0=360),
                qnum(2, y0=400, isolated=True),
                line("Which drying agent is used?", x0=101.3, y0=402),
                line("A", x0=101.3, y0=430),
                line("calcium oxide", x0=129, y0=430),
                line("B", x0=101.3, y0=450),
                line("concentrated sulfuric acid", x0=129, y0=450),
                line("C", x0=101.3, y0=470),
                line("phosphorus(V) oxide", x0=129, y0=470),
                line("D", x0=101.3, y0=490),
                line("silica gel", x0=129, y0=490),
            ],
            expected_count=2,
        )
    assert [q.question_number for q in paper.questions] == [1, 2]
    assert "1" in paper.questions[0].stem


def test_docling_inline_option_line_is_not_duplicated():
    paper = _parse(
        [
            qnum(1, y0=80, isolated=False, stem="Which apparatus must she use?"),
            line("A 1, 2, 3 and 4", x0=101.3, y0=120),
            line("B 1, 4 and 6", x0=101.3, y0=140),
            line("C 1, 5 and 6", x0=101.3, y0=160),
            line("D 2, 4, 5 and 6", x0=101.3, y0=180),
        ]
    )
    options = paper.questions[0].options
    assert options["A"].text == "1, 2, 3 and 4"
    assert options["B"].text == "1, 4 and 6"
    assert options["C"].text == "1, 5 and 6"
    assert options["D"].text == "2, 4, 5 and 6"


def test_option_a_chemical_name_is_not_english_article():
    """Q11-style: 'A ammonium chloride' must not be skipped as English 'A ...'."""
    paper = _parse(
        [
            qnum(
                1,
                y0=216,
                isolated=False,
                stem="Which of the following compounds does not have both covalent and ionic bonding?",
            ),
            line("A ammonium chloride", x0=101.3, y0=238),
            line("B copper( II ) carbonate", x0=101.3, y0=254),
            line("C phosphorus pentachloride", x0=101.3, y0=270),
            line("D sodium nitrate", x0=101.3, y0=285),
        ]
    )
    question = paper.questions[0]
    assert "ammonium chloride" not in question.stem
    assert question.options["A"].text == "ammonium chloride"
    assert question.options["B"].text == "copper( II ) carbonate"
    assert question.options["C"].text == "phosphorus pentachloride"
    assert question.options["D"].text == "sodium nitrate"


def test_inline_abcd_on_single_docling_line():
    paper = _parse(
        [
            qnum(1, y0=80, isolated=False, stem="Which tests work?"),
            line("A 1, 2 and 3 B 1 and 2 only C 1 and 3 only D 2 and 3 only", x0=101.3, y0=120, x1=520),
        ]
    )
    options = paper.questions[0].options
    assert options["A"].text == "1, 2 and 3"
    assert options["B"].text == "1 and 2 only"
    assert options["C"].text == "1 and 3 only"
    assert options["D"].text == "2 and 3 only"


def test_stem_table_is_structured_and_not_flattened_into_stem():
    table = TableRegion(
        page=1,
        bbox=BoundingBox(x0=100, y0=100, x1=540, y1=300),
        headers=["substance", "composition", "conductivity", "effect of heat"],
        rows=[
            ["P", "constant", "yes", "solid burns in air to form an oxide"],
            ["Q", "varies", "no", "liquid burns to form carbon dioxide and water"],
        ],
        row_count=3,
        col_count=4,
    )
    paper = _parse(
        [
            qnum(1, y0=80),
            line("Some properties of substances P, Q, R and S are given in the table below.", x0=101.3, y0=82),
            line("substance", x0=110, y0=110, x1=180, y1=122),
            line("P", x0=110, y0=140, x1=130, y1=152),
            line("constant", x0=200, y0=140, x1=260, y1=152),
            line("Which classification is correct?", x0=101.3, y0=320),
            line("A", x0=101.3, y0=360),
            line("P is an element", x0=129, y0=360),
            line("B", x0=101.3, y0=380),
            line("Q is a mixture", x0=129, y0=380),
            line("C", x0=101.3, y0=400),
            line("R is a compound", x0=129, y0=400),
            line("D", x0=101.3, y0=420),
            line("S is an element", x0=129, y0=420),
        ],
        tables=[table],
    )
    question = paper.questions[0]
    assert "table below" in question.stem
    assert "Which classification is correct?" in question.stem
    assert "constant" not in question.stem
    assert "solid burns" not in question.stem
    assert len(question.tables) == 1
    assert question.tables[0].role == "stem"
    assert question.tables[0].rows[0][0] == "P"


def test_option_table_headers_are_not_appended_to_stem():
    table = TableRegion(
        page=1,
        bbox=BoundingBox(x0=95, y0=110, x1=550, y1=220),
        headers=["", "element", "mixture", "compound"],
        rows=[["A | B | C | D", "P | P | R | S", "Q, S | S | Q, S | Q", "R | Q, R | P | P, R"]],
        row_count=2,
        col_count=4,
    )
    paper = _parse(
        [
            qnum(1, y0=80, isolated=False, stem="Which classification is correct?"),
            line("element", x0=161, y0=120, x1=220, y1=132),
            line("mixture", x0=269, y0=120, x1=330, y1=132),
            line("compound", x0=381, y0=120, x1=460, y1=132),
            line("A", x0=101.3, y0=150),
            line("P", x0=174, y0=150),
            line("Q, S", x0=286, y0=150),
            line("R", x0=398, y0=150),
            line("B", x0=101.3, y0=170),
            line("P", x0=174, y0=170),
            line("S", x0=286, y0=170),
            line("Q, R", x0=398, y0=170),
            line("C", x0=101.3, y0=190),
            line("R", x0=174, y0=190),
            line("Q, S", x0=286, y0=190),
            line("P", x0=398, y0=190),
            line("D", x0=101.3, y0=210),
            line("S", x0=174, y0=210),
            line("Q", x0=286, y0=210),
            line("P, R", x0=398, y0=210),
        ],
        tables=[table],
    )
    question = paper.questions[0]
    assert question.stem == "Which classification is correct?"
    assert question.tables[0].role == "options"
    assert "element" in question.tables[0].headers
    assert "mixture" in question.tables[0].headers
    assert "compound" in question.tables[0].headers
    assert question.options["A"].text == "P Q, S R"


def test_graph_axis_labels_are_stripped_from_stem():
    paper = _parse(
        [
            qnum(1, y0=80),
            line("The graph below shows the yield of ammonia from Haber process at different", x0=101.3, y0=82),
            line("0 100 200 300 400", x0=180, y0=120, x1=400, y1=140),
            line("Which of the following statements can be inferred from the graph?", x0=101.3, y0=220),
            line("A", x0=101.3, y0=250),
            line("yield increases with pressure", x0=129, y0=250),
            line("B", x0=101.3, y0=270),
            line("yield decreases with pressure", x0=129, y0=270),
            line("C", x0=101.3, y0=290),
            line("temperature has no effect", x0=129, y0=290),
            line("D", x0=101.3, y0=310),
            line("a catalyst is not used", x0=129, y0=310),
        ],
        images=[
            ImageRegion(
                page=1,
                bbox=BoundingBox(x0=170, y0=90, x1=480, y1=200),
                block_index=20,
            )
        ],
    )
    stem = paper.questions[0].stem
    assert "yield of ammonia" in stem
    assert "inferred from the graph" in stem
    assert "0 100 200 300 400" not in stem
    assert paper.questions[0].visual.required is True


def test_table_overlapping_graph_image_is_ignored():
    paper = _parse(
        [
            qnum(1, y0=80),
            line("The following shows the heating curve of ice.", x0=101.3, y0=82),
            line("Which description in the table below best explains the graph?", x0=101.3, y0=220),
            line("A", x0=101.3, y0=250),
            line("P to Q particles are stationary", x0=129, y0=250),
            line("B", x0=101.3, y0=270),
            line("Q to R bonds break", x0=129, y0=270),
            line("C", x0=101.3, y0=290),
            line("R to S particles expand", x0=129, y0=290),
            line("D", x0=101.3, y0=310),
            line("T to U water boils", x0=129, y0=310),
        ],
        images=[
            ImageRegion(page=1, bbox=BoundingBox(x0=220, y0=100, x1=420, y1=190), block_index=20)
        ],
        tables=[
            TableRegion(
                page=1,
                bbox=BoundingBox(x0=221, y0=114, x1=418, y1=274),
                headers=["U S T Q R P time/min", ""],
                rows=[["", "time/min"]],
                row_count=2,
                col_count=2,
            )
        ],
    )
    question = paper.questions[0]
    assert question.tables == []
    assert "heating curve" in question.stem

