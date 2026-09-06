from __future__ import annotations

import re
from dataclasses import dataclass

from questbank.types.layout import PaperLayout, TextLine

_QUESTION_START = re.compile(r"^(?:Q\s*)?([1-9]\d?)(?:[\.\)]\s*|\s*$|\s+)(.*)$", re.I)
_ANSWERS_START = re.compile(r"(?i)^(?:answers?\b|mark\s*scheme\b|suggested\s+answers?\b)")
_PAGE_ONLY = re.compile(r"^\d{1,3}$")
_TITLE_NOISE = re.compile(
    r"(?i)^(?:o\s*level|pure\s+chemistry|ammonia\s+test|structured\b)"
)


@dataclass(frozen=True)
class StructuredStart:
    number: int
    line: TextLine
    stem_prefix: str
    line_index: int


@dataclass(frozen=True)
class StructuredSlice:
    number: int
    start: StructuredStart
    lines: list[TextLine]
    page_start: int
    page_end: int


def find_answers_section_index(layout: PaperLayout) -> tuple[int | None, int | None]:
    """Return (line_index, page) of the Answers section, if present."""
    for index, line in enumerate(layout.lines_in_reading_order()):
        if _ANSWERS_START.match(line.text.strip()):
            return index, line.page
    return None, None


def find_answers_section_page(layout: PaperLayout) -> int | None:
    _, page = find_answers_section_index(layout)
    return page


def detect_structured_boundaries(
    layout: PaperLayout,
    *,
    stop_at_answers: bool = True,
) -> list[StructuredSlice]:
    """Find Q1…Qn starts for structured papers; optionally stop before Answers."""
    lines = layout.lines_in_reading_order()
    answers_index, _answers_page = (
        find_answers_section_index(layout) if stop_at_answers else (None, None)
    )
    usable = lines[:answers_index] if answers_index is not None else lines

    starts: list[StructuredStart] = []
    for index, line in enumerate(usable):
        text = line.text.strip()
        if _PAGE_ONLY.match(text) or _TITLE_NOISE.match(text):
            continue
        match = _QUESTION_START.match(text)
        if not match:
            continue
        number = int(match.group(1))
        if starts and number <= starts[-1].number:
            continue
        # Prefer explicit Q-prefixed labels or leftish numbers.
        if not text.upper().startswith("Q") and line.x0 > 120:
            continue
        prefix = (match.group(2) or "").strip()
        starts.append(
            StructuredStart(
                number=number,
                line=line,
                stem_prefix=prefix,
                line_index=index,
            )
        )

    slices: list[StructuredSlice] = []
    for index, start in enumerate(starts):
        end_index = starts[index + 1].line_index if index + 1 < len(starts) else len(usable)
        chunk = usable[start.line_index : end_index]
        if not chunk:
            continue
        slices.append(
            StructuredSlice(
                number=start.number,
                start=start,
                lines=chunk,
                page_start=chunk[0].page,
                page_end=chunk[-1].page,
            )
        )
    return slices
