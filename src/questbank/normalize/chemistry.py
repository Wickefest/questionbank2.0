from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

TokenKind = Literal["formula", "unit", "isotope", "state"]

# Prefer tokens that look like formulae (digit or multi-element), not plain English.
# Optional trailing ionic charge (V3+, VO2+, Fe2+) is part of the token.
_FORMULA = re.compile(
    r"(?<![A-Za-z0-9])("
    r"(?:"
    r"[A-Z][a-z]?(?:\s*\d+)+(?:[A-Z][a-z]?(?:\s*\d+)*)*"
    r"|[A-Z][a-z]?(?:[A-Z][a-z]?\d*)+"
    r"|[A-Z][a-z]?\d*[+-]"  # single-element ions (V3+, H+, Cl-)
    r")"
    r"(?:\.(?:\d+)?(?:H\s*2\s*O|H₂O))?"
    r"(?:\s*\(\s*[IVX]+\s*\))?"
    r"(?:\d*[+-])?"  # ionic charge glued to formula (not "H2 + Cl2" reaction plus)
    r")(?![A-Za-z])"
)

_UNIT = re.compile(
    r"(?<![A-Za-z0-9])("
    r"cm\s*3|cm\s*³|dm\s*3|dm\s*³|"
    r"mol\s*/\s*dm\s*-?\s*3|mol\s*dm\s*-?\s*3|"
    r"mol\s*dm⁻³|g\s*/\s*mol|°C|%\s*by\s*mass|"
    r"atm(?:ospheres?)?|kPa|kJ(?:\s*/\s*mol)?"
    r")(?![A-Za-z0-9])",
    re.I,
)

_ISOTOPE = re.compile(r"(?<![A-Za-z0-9])((?:\d{1,3}\s*)?[A-Z][a-z]?(?:\s*\d+[+-]?|\d+[+-]?))(?![A-Za-z])")
_STATE = re.compile(r"\(\s*(s|l|g|aq)\s*\)", re.I)

_SUBSCRIPT = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_SUPERSCRIPT = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")
_ASCII_FROM_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")

_UNIT_MAP = (
    (re.compile(r"(?i)cm\s*3|cm\s*³"), "cm³"),
    (re.compile(r"(?i)dm\s*3|dm\s*³"), "dm³"),
    (re.compile(r"(?i)mol\s*/\s*dm\s*-?\s*3|mol\s*dm\s*-?\s*3|mol\s*dm⁻³"), "mol dm⁻³"),
    (re.compile(r"(?i)g\s*/\s*mol"), "g/mol"),
    (re.compile(r"(?i)atmospheres?"), "atm"),
    (re.compile(r"(?i)kJ\s*/\s*mol"), "kJ/mol"),
)

# OCR/LLM often drops ⇌ and glues the product coefficient onto the last reactant
# e.g. "N2 + 3H22NH3" instead of "N₂ + 3H₂ ⇌ 2NH₃".
_EQUATION_REPAIRS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        # Glued form with no space/arrow: N2 + 3H22NH3
        re.compile(r"N\s*[₂2]\s*\+\s*3\s*H\s*[₂2]\s*2\s*NH\s*[₃3]", re.I),
        "N₂ + 3H₂ ⇌ 2NH₃",
    ),
    (
        re.compile(
            r"N\s*[₂2]\s*\+\s*3\s*H\s*[₂2]\s*(?:⇌|<=>|↔|=)\s*2\s*NH\s*[₃3]",
            re.I,
        ),
        "N₂ + 3H₂ ⇌ 2NH₃",
    ),
    (
        re.compile(
            r"4\s*NH\s*[₃3]\s*\(\s*g\s*\)\s*\+\s*5\s*O\s*[₂2]\s*\(\s*g\s*\)\s*"
            r"(?:→|->|⇌|<=>)?\s*4\s*NO\s*\(\s*g\s*\)\s*\+\s*6\s*H\s*[₂2]\s*O\s*\(\s*g\s*\)",
            re.I,
        ),
        "4NH₃(g) + 5O₂(g) → 4NO(g) + 6H₂O(g)",
    ),
    (
        re.compile(
            r"4\s*NO\s*\(\s*g\s*\)\s*\+\s*2\s*H\s*[₂2]\s*O\s*\(\s*g\s*\)\s*\+\s*3\s*O\s*[₂2]\s*\(\s*g\s*\)\s*"
            r"(?:→|->|⇌|<=>)?\s*4\s*HNO\s*[₃3]\s*\(\s*aq\s*\)",
            re.I,
        ),
        "4NO(g) + 2H₂O(g) + 3O₂(g) → 4HNO₃(aq)",
    ),
)

_GLUED_EQUILIBRIUM = re.compile(
    r"(?<![A-Za-z0-9])"
    r"((?:\d+\s*)?[A-Z][a-z]?(?:[₀-₉0-9]+)?(?:[A-Z][a-z]?(?:[₀-₉0-9]+)*)*)"
    r"\s*\+\s*"
    r"((?:\d+\s*)?[A-Z][a-z]?(?:[₀-₉0-9]+)?(?:[A-Z][a-z]?(?:[₀-₉0-9]+)*)*)"
    r"(\d+)"  # product stoichiometric coefficient glued after last reactant subscript
    r"([A-Z][a-z]?(?:[₀-₉0-9]+)?(?:[A-Z][a-z]?(?:[₀-₉0-9]+)*)*)"
    r"(?![A-Za-z])"
)

_DELTA_H = re.compile(r"[∆Δ]\s*H\s*=\s*(-?\s*[\d.]+)\s*(kJ(?:\s*/\s*mol)?)", re.I)
_ARROW_NORMALIZE = (
    (re.compile(r"\s*(?:<=>|<->|↔)\s*"), " ⇌ "),
    (re.compile(r"\s*(?:->|→)\s*"), " → "),
)


class ChemistryToken(BaseModel):
    raw: str
    kind: TokenKind
    normalized: str
    start: int | None = None
    end: int | None = None


class ChemistryAnnotations(BaseModel):
    """API-facing chemistry hints. Original stem/option text stays untouched."""

    tokens: list[ChemistryToken] = Field(default_factory=list)
    stem_normalized: str | None = Field(default=None, serialization_alias="stemNormalized")
    options_normalized: dict[str, str] = Field(
        default_factory=dict, serialization_alias="optionsNormalized"
    )

    model_config = {"populate_by_name": True}


def annotate_chemistry(stem: str, options: dict[str, str | None]) -> ChemistryAnnotations:
    tokens = _extract_tokens(stem)
    options_normalized: dict[str, str] = {}
    for label, text in options.items():
        if not text:
            continue
        tokens.extend(_extract_tokens(text))
        options_normalized[label] = normalize_chemistry_text(text)
    # de-dupe tokens by (kind, normalized, raw) preserving order
    seen: set[tuple[str, str, str]] = set()
    unique: list[ChemistryToken] = []
    for token in tokens:
        key = (token.kind, token.normalized, token.raw)
        if key in seen:
            continue
        seen.add(key)
        unique.append(token)
    return ChemistryAnnotations(
        tokens=unique,
        stem_normalized=normalize_chemistry_text(stem),
        options_normalized=options_normalized,
    )


def normalize_chemistry_text(text: str) -> str:
    """Repair mangled equations, then normalize formulas/units/states."""
    if not text:
        return text
    result = latex_chemistry_to_unicode(text)
    # Re-parse scripts so V₃+ / VO₂+ become proper charges after heuristics.
    result = _flatten_script_digits(result)
    result = repair_chemistry_equations(result)
    # Glue "H 2" / "C 3 H 8" BEFORE subscript normalization.
    result = glue_formula_digits(result)
    for pattern, replacement in _UNIT_MAP:
        result = pattern.sub(replacement, result)

    def _formula_sub(match: re.Match[str]) -> str:
        raw = match.group(1)
        if re.fullmatch(r"[A-D]\s*\d+", raw):
            return raw
        return normalize_formula_token(raw)

    result = _FORMULA.sub(_formula_sub, result)
    result = _STATE.sub(lambda m: f"({m.group(1).lower()})", result)
    result = _DELTA_H.sub(
        lambda m: f"ΔH = {m.group(1).replace(' ', '')} {m.group(2).replace(' ', '')}",
        result,
    )
    for pattern, replacement in _ARROW_NORMALIZE:
        result = pattern.sub(replacement, result)
    return " ".join(result.split())


_SPACED_FORMULA = re.compile(
    r"(?<![A-Za-z0-9])("
    r"(?:\d+\s*)?"
    r"[A-Z][a-z]?"
    r"(?:\s+\d+)+"
    r"(?:\s*[A-Z][a-z]?(?:\s+\d+)*)*"
    r")(?![A-Za-z])"
)


def glue_formula_digits(text: str) -> str:
    """Stick spaced formula digits to elements before normalizing (H 2 → H2)."""
    if not text:
        return text

    def _glue(match: re.Match[str]) -> str:
        raw = match.group(1)
        # Keep MCQ artefacts like "A 15" alone.
        if re.fullmatch(r"[A-D]\s+\d+", raw):
            return raw
        return re.sub(r"\s+", "", raw)

    return _SPACED_FORMULA.sub(_glue, text)

def repair_chemistry_equations(text: str) -> str:
    """Fix common OCR/LLM equation failures (dropped ⇌, glued coefficients)."""
    if not text:
        return text
    result = text
    for pattern, replacement in _EQUATION_REPAIRS:
        result = pattern.sub(replacement, result)

    def _unglue(match: re.Match[str]) -> str:
        left = match.group(1).strip()
        mid = match.group(2).strip()
        coeff = match.group(3)
        product = match.group(4).strip()
        # Only unglue when the middle species ends with a digit/subscript (formula)
        # and the glued coeff looks stoichiometric (1-20).
        mid_ascii = mid.translate(_ASCII_FROM_SUB)
        if not re.search(r"\d$", mid_ascii):
            return match.group(0)
        if not (1 <= int(coeff) <= 20):
            return match.group(0)
        return f"{left} + {mid} ⇌ {coeff}{product}"

    result = _GLUED_EQUILIBRIUM.sub(_unglue, result)
    return result


def normalize_formula_token(raw: str) -> str:
    compact = re.sub(r"\s+", "", raw)
    # Flatten accidental HTML / unicode so charge heuristics see ASCII digits.
    compact = _flatten_script_digits(compact)
    # Keep Roman oxidation states in parentheses as-is.
    parts = re.split(r"(\([IVX]+\))", compact)
    rebuilt: list[str] = []
    for part in parts:
        if re.fullmatch(r"\([IVX]+\)", part or ""):
            rebuilt.append(part)
            continue
        rebuilt.append(_apply_subscripts(part or ""))
    return "".join(rebuilt)


def _flatten_script_digits(text: str) -> str:
    """Map sub/superscript digits back to ASCII before re-applying chemistry rules."""
    text = re.sub(r"</?sub>", "", text, flags=re.I)
    text = re.sub(r"</?sup>", "", text, flags=re.I)
    text = text.translate(_ASCII_FROM_SUB)
    text = text.translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-"))
    return text


def _apply_subscripts(text: str) -> str:
    """Element digits → subscript; ionic charges → superscript.

    Single-element ions keep charge digits as superscript (V3+ → V³⁺).
    Multi-element formulas treat mid digits as stoichiometry (VO2+ → VO₂⁺).
    """
    out: list[str] = []
    index = 0
    elements_seen = 0
    while index < len(text):
        element = re.match(r"[A-Z][a-z]?", text[index:])
        if element:
            out.append(element.group(0))
            index += element.end()
            elements_seen += 1
            digits = re.match(r"\d+", text[index:])
            if digits:
                after = text[index + digits.end() :]
                # V3+ / Fe2+: only one element so far and the token ends in a sign.
                if elements_seen == 1 and re.fullmatch(r"[+-]", after or ""):
                    out.append((digits.group(0) + after).translate(_SUPERSCRIPT))
                    index = len(text)
                    continue
                out.append(digits.group(0).translate(_SUBSCRIPT))
                index += digits.end()
            continue
        charge = re.match(r"(\d+)?[+-]", text[index:])
        if charge and index > 0:
            out.append(charge.group(0).translate(_SUPERSCRIPT))
            index += charge.end()
            continue
        out.append(text[index])
        index += 1
    return "".join(out)


_LATEX_COMMANDS = (
    (re.compile(r"\\mathrm\{([^{}]*)\}"), r"\1"),
    (re.compile(r"\\text\{([^{}]*)\}"), r"\1"),
    (re.compile(r"\\ce\{([^{}]*)\}"), r"\1"),
    (re.compile(r"\\left|\\right"), ""),
    # Vision models sometimes invent includegraphics / array instead of visual flags.
    (re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{[^{}]*\}"), ""),
    (re.compile(r"\\begin\{array\}(?:\{[^{}]*\})?|\\end\{array\}"), ""),
)
_LATEX_SUB = re.compile(r"_(\d)|_\{+([^{}]+)\}+")
_LATEX_SUP = re.compile(r"\^(\d+[+-]?|[+-])|\^\{+([^{}]+)\}+")
_LATEX_WRAP = re.compile(r"\$\$?|\\\(|\\\)|\\\[|\\\]")


def latex_chemistry_to_unicode(text: str) -> str:
    """Convert light chemistry LaTeX (sub/sup) into Unicode for storage/display."""
    if not text or ("\\" not in text and "_" not in text and "^" not in text and "$" not in text):
        return text

    # Prompt/JSON escaping often yields V^{{3+}} / VO_2^{{+}}.
    result = text.replace("{{", "{").replace("}}", "}")
    result = _LATEX_WRAP.sub("", result)
    for pattern, repl in _LATEX_COMMANDS:
        result = pattern.sub(repl, result)

    def _sub(match: re.Match[str]) -> str:
        body = match.group(1) or match.group(2) or ""
        return body.translate(_SUBSCRIPT)

    def _sup(match: re.Match[str]) -> str:
        body = match.group(1) or match.group(2) or ""
        return body.translate(_SUPERSCRIPT)

    # Nested-ish: apply a few passes for NH_4^+ / VO_2^+
    for _ in range(4):
        nxt = _LATEX_SUB.sub(_sub, result)
        nxt = _LATEX_SUP.sub(_sup, nxt)
        if nxt == result:
            break
        result = nxt
    return " ".join(result.replace("{}", "").split())


def _extract_tokens(text: str) -> list[ChemistryToken]:
    if not text:
        return []
    tokens: list[ChemistryToken] = []
    for match in _UNIT.finditer(text):
        raw = match.group(1)
        tokens.append(
            ChemistryToken(
                raw=raw,
                kind="unit",
                normalized=_normalize_unit(raw),
                start=match.start(1),
                end=match.end(1),
            )
        )
    for match in _STATE.finditer(text):
        raw = match.group(0)
        tokens.append(
            ChemistryToken(
                raw=raw,
                kind="state",
                normalized=f"({match.group(1).lower()})",
                start=match.start(),
                end=match.end(),
            )
        )
    for match in _FORMULA.finditer(text):
        raw = match.group(1)
        compact = re.sub(r"\s+", "", raw)
        if len(compact) < 2:
            continue
        if _UNIT.fullmatch(raw):
            continue
        # Avoid MCQ artefacts like "A 15" / "B 2".
        if re.fullmatch(r"[A-D]\s*\d+", raw):
            continue
        tokens.append(
            ChemistryToken(
                raw=raw,
                kind="formula",
                normalized=normalize_formula_token(raw),
                start=match.start(1),
                end=match.end(1),
            )
        )
    return tokens


def _normalize_unit(raw: str) -> str:
    for pattern, replacement in _UNIT_MAP:
        if pattern.fullmatch(raw.strip()):
            return replacement
    return " ".join(raw.split())
