from __future__ import annotations

from questbank.normalize.chemistry import annotate_chemistry, normalize_chemistry_text, normalize_formula_token
from questbank.parsers.chemistry.parse_tables import _normalize_table_matrix


def test_normalize_formula_and_units():
    assert normalize_formula_token("H 2 O") == "H₂O"
    assert normalize_formula_token("C 3 H 8") == "C₃H₈"
    assert normalize_formula_token("CuSO4") == "CuSO₄"
    text = normalize_chemistry_text("14 g of nitrogen, N2 in 24 dm 3 at 30°C and 1.00 mol dm-3")
    assert "N₂" in text
    assert "dm³" in text
    assert "mol dm⁻³" in text
    assert "A₁₅" not in normalize_chemistry_text("A 15 cm3 sample")
    assert "cm³" in normalize_chemistry_text("A 15 cm3 sample")


def test_annotate_chemistry_keeps_original_and_adds_api_fields():
    ann = annotate_chemistry(
        "What is the mass of oxalic acid C2H2O4.2H2O in 100 cm3?",
        {"A": "1.26 g", "B": "24 dm 3 of CO2"},
    )
    assert ann.stem_normalized is not None
    assert "cm³" in (ann.stem_normalized or "")
    assert any(token.kind == "unit" for token in ann.tokens)
    assert any(token.kind == "formula" for token in ann.tokens)
    assert "B" in ann.options_normalized


def test_option_table_headers_preserved_and_rows_aligned():
    headers, rows = _normalize_table_matrix(
        ["", "section", "description"],
        [
            ["P to Q", "The particles are stationary", "A"],
            ["Q to R", "bonds break", "B"],
            ["R to S", "particles expand", "C"],
            ["T to U", "water boils", "D"],
        ],
        "options",
    )
    assert headers == ["", "section", "description"]
    assert rows[0] == ["A", "P to Q", "The particles are stationary"]
    assert rows[1][0] == "B"
    assert rows[3] == ["D", "T to U", "water boils"]
