from __future__ import annotations

from questbank.normalize.chemistry import annotate_chemistry, normalize_chemistry_text, normalize_formula_token
from questbank.parsers.chemistry.parse_tables import _normalize_table_matrix


def test_glue_formula_digits_before_normalize():
    from questbank.normalize.chemistry import glue_formula_digits

    assert glue_formula_digits("H 2 O and C 3 H 8") == "H2O and C3H8"
    assert "H₂O" in normalize_chemistry_text("contains H 2 O")
    assert "C₃H₈" in normalize_chemistry_text("alkane C 3 H 8")
    # Do not glue option-label artefacts.
    assert glue_formula_digits("A 15 cm3") == "A 15 cm3"


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


def test_ionic_charges_are_superscript_not_subscript():
    assert normalize_formula_token("V3+") == "V³⁺"
    assert normalize_formula_token("VO2+") == "VO₂⁺"
    assert normalize_formula_token("Fe2+") == "Fe²⁺"
    assert normalize_formula_token("NH4+") == "NH₄⁺"
    # Already-mangled OCR/LLM forms should be repaired.
    assert "V³⁺" in normalize_chemistry_text("B V₃+")
    assert "VO₂⁺" in normalize_chemistry_text("C VO₂+")
    assert "NH₄VO₃" in normalize_chemistry_text("A NH4VO3")


def test_latex_chemistry_to_unicode():
    from questbank.normalize.chemistry import latex_chemistry_to_unicode

    assert "V³⁺" in latex_chemistry_to_unicode(r"V^{3+}")
    assert "VO₂⁺" in latex_chemistry_to_unicode(r"VO_2^{+}")
    assert "VO₂⁺" in latex_chemistry_to_unicode(r"VO_2^{{+}}")
    assert "NH₄VO₃" in latex_chemistry_to_unicode(r"NH_4VO_3")
    assert "H₂O" in normalize_chemistry_text(r"contains H_2O and V^{3+}")
    assert normalize_chemistry_text(r"VO₂^{{+}}") == "VO₂⁺"


def test_repair_haber_equation_glued_arrow():
    from questbank.normalize.chemistry import repair_chemistry_equations

    mangled = "Ammonia is manufactured by the Haber Process. N2 + 3H22NH3 ∆ H = -92.4 kJ/mol"
    fixed = normalize_chemistry_text(mangled)
    assert "N₂ + 3H₂ ⇌ 2NH₃" in fixed
    assert "H22NH3" not in fixed
    assert "ΔH = -92.4 kJ/mol" in fixed
    assert repair_chemistry_equations("N2 + 3H22NH3") == "N₂ + 3H₂ ⇌ 2NH₃"


def test_repair_glued_equilibrium_generic():
    from questbank.normalize.chemistry import repair_chemistry_equations

    assert "⇌" in repair_chemistry_equations("H2 + Cl22HCl")
    text = normalize_chemistry_text("H2 + Cl22HCl")
    assert "H₂" in text
    assert "HCl" in text or "2HCl" in text


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
