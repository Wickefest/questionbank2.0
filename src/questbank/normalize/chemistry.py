from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

TokenKind = Literal["formula", "unit", "isotope", "state"]

# Prefer tokens that look like formulae (digit or multi-element), not plain English.
_FORMULA = re.compile(
    r"(?<![A-Za-z0-9])("
    r"(?:"
    r"[A-Z][a-z]?(?:\s*\d+)+(?:[A-Z][a-z]?(?:\s*\d+)*)*"
    r"|[A-Z][a-z]?(?:[A-Z][a-z]?\d*)+"
    r")"
    r"(?:\.(?:\d+)?(?:H\s*2\s*O|H₂O))?"
    r"(?:\s*\(\s*[IVX]+\s*\))?"
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

_UNIT_MAP = (
    (re.compile(r"(?i)cm\s*3|cm\s*³"), "cm³"),
    (re.compile(r"(?i)dm\s*3|dm\s*³"), "dm³"),
    (re.compile(r"(?i)mol\s*/\s*dm\s*-?\s*3|mol\s*dm\s*-?\s*3|mol\s*dm⁻³"), "mol dm⁻³"),
    (re.compile(r"(?i)g\s*/\s*mol"), "g/mol"),
    (re.compile(r"(?i)atmospheres?"), "atm"),
    (re.compile(r"(?i)kJ\s*/\s*mol"), "kJ/mol"),
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
    if not text:
        return text
    result = text
    for pattern, replacement in _UNIT_MAP:
        result = pattern.sub(replacement, result)

    def _formula_sub(match: re.Match[str]) -> str:
        raw = match.group(1)
        if re.fullmatch(r"[A-D]\s*\d+", raw):
            return raw
        return normalize_formula_token(raw)

    result = _FORMULA.sub(_formula_sub, result)
    result = _STATE.sub(lambda m: f"({m.group(1).lower()})", result)
    return " ".join(result.split())


def normalize_formula_token(raw: str) -> str:
    compact = re.sub(r"\s+", "", raw)
    # Keep Roman oxidation states in parentheses as-is.
    parts = re.split(r"(\([IVX]+\))", compact)
    rebuilt: list[str] = []
    for part in parts:
        if re.fullmatch(r"\([IVX]+\)", part or ""):
            rebuilt.append(part)
            continue
        rebuilt.append(_apply_subscripts(part or ""))
    return "".join(rebuilt)


def _apply_subscripts(text: str) -> str:
    # Element then digits → subscript; trailing charge digits/sign → superscript.
    out: list[str] = []
    index = 0
    while index < len(text):
        element = re.match(r"[A-Z][a-z]?", text[index:])
        if element:
            out.append(element.group(0))
            index += element.end()
            digits = re.match(r"\d+", text[index:])
            if digits:
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
