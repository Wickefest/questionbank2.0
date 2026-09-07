from __future__ import annotations

import re
from dataclasses import dataclass

from questbank.types.layout import PaperLayout, TextLine

QUESTION_MIN = 1
# Soft upper bound for candidate scanning; detect_question_boundaries also
# clamps to the caller-supplied expected_count (fixture param, not universal).
QUESTION_MAX = 99

_LEFT_MARGIN_MAX_X0 = 90.0
_HEADER_Y = 50.0
_FOOTER_INSET = 50.0
_ISOLATED_NUMBER = re.compile(r"^\d{1,2}$")
_NUMBER_THEN_STEM = re.compile(r"^(?:Q\s*)?(\d{1,2})(?:[\.\)]\s*|\s+)(\S.*)$", re.I)
_FURNITURE = re.compile(
    r"(?i)^(?:kcpss\b|\[turn over|turn over\]?|section a\b|end of (?:section|paper)"
    r"|-\s*end of section\s*-?"
    r"|this document consists|chemistry\s+6092|paper 1 multiple choice"
    r"|preliminary examination|multiple choice answer sheet|additional materials"
    r"|kuo chuan|secondary school)"
)
_FALSE_STEM = re.compile(
    r"(?i)^(?:"
    r"hour\b|express\b|multiple choice\b|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"iron\b|steel\b|diamond\b|graphite\b|"
    r"fractional distillation\b|evaporation\b|filtration\b|use of a separating funnel\b|"
    r"and \d+ only\b|only\b"
    r")"
)
_QUESTIONISH_STEM = re.compile(
    r"(?i)^(?:"
    r"the |which |what |how |when |where |why |a |an |in |refer |"
    r"some |element |solutions? |oxalic |propyl |metals? |hydrazine |"
    r"a student|a mixture|a sample|a molecule|a section|an element|an aqueous|"
    r"solutions p|the elements|the element|the diagram|the graph|the apparatus|"
    r"the following|the structures|the reactions|the isotopes"
    r")"
)
_ISOTOPE_LIKE = re.compile(r"^\d{2,3}\s+[A-Za-z]")


@dataclass(frozen=True)
class QuestionStart:
    number: int
    line: TextLine
    stem_prefix: str
    line_index: int


@dataclass(frozen=True)
class QuestionSlice:
    number: int
    start: QuestionStart
    lines: list[TextLine]
    page_start: int
    page_end: int


def is_page_furniture(line: TextLine, page_height: float) -> bool:
    if line.y0 < _HEADER_Y:
        return True
    if line.y0 > page_height - _FOOTER_INSET:
        return True
    return bool(_FURNITURE.search(line.text.strip()))


def detect_question_boundaries(
    layout: PaperLayout,
    expected_count: int = 40,
) -> list[QuestionSlice]:
    """Find Q1–Q40 using left-margin geometry and monotonic numbering."""
    page_heights = {page.page_number: page.height for page in layout.pages}
    lines = layout.lines_in_reading_order()
    starts = _select_starts(lines, page_heights, expected_count)
    return _slices_from_starts(starts, lines, page_heights)


def _select_starts(
    lines: list[TextLine],
    page_heights: dict[int, float],
    expected_count: int,
) -> list[QuestionStart]:
    candidates = [
        start
        for index, line in enumerate(lines)
        if (start := _candidate_start(line, index, page_heights.get(line.page, 842.0)))
    ]
    selected: list[QuestionStart] = []
    expected = QUESTION_MIN
    for candidate in candidates:
        if candidate.number == expected and candidate.number <= expected_count:
            selected.append(candidate)
            expected += 1
            continue
        if candidate.number < expected:
            continue
        # Allow a small gap only after at least one real question is locked in.
        # This avoids cover-page "25 August" jumping from a false Q1.
        if selected and candidate.number <= expected_count and candidate.number <= expected + 2:
            selected.append(candidate)
            expected = candidate.number + 1
    return selected


def _candidate_start(
    line: TextLine, line_index: int, page_height: float
) -> QuestionStart | None:
    if is_page_furniture(line, page_height):
        return None
    if line.x0 > _LEFT_MARGIN_MAX_X0:
        return None

    text = line.text.strip()
    isolated = _ISOLATED_NUMBER.fullmatch(text)
    if isolated:
        number = int(isolated.group(0))
        if QUESTION_MIN <= number <= QUESTION_MAX:
            return QuestionStart(number, line, "", line_index)
        return None

    match = _NUMBER_THEN_STEM.match(text)
    if not match:
        return None
    number = int(match.group(1))
    if not (QUESTION_MIN <= number <= QUESTION_MAX):
        return None
    stem_prefix = match.group(2).strip()
    if not _looks_like_question_stem(stem_prefix):
        return None
    return QuestionStart(number, line, stem_prefix, line_index)


def _looks_like_question_stem(stem: str) -> bool:
    collapsed = " ".join(stem.split())
    if not collapsed:
        return True
    if _FALSE_STEM.match(collapsed):
        return False
    if _ISOTOPE_LIKE.match(collapsed):
        return False
    if collapsed.endswith("?"):
        return True
    if _QUESTIONISH_STEM.match(collapsed):
        return True
    # Unusual openings are allowed only when the stem is clearly long prose.
    return len(collapsed) >= 60


def _slices_from_starts(
    starts: list[QuestionStart],
    lines: list[TextLine],
    page_heights: dict[int, float],
) -> list[QuestionSlice]:
    slices: list[QuestionSlice] = []
    for index, start in enumerate(starts):
        end_index = starts[index + 1].line_index if index + 1 < len(starts) else len(lines)
        region = [
            line
            for line in lines[start.line_index : end_index]
            if not is_page_furniture(line, page_heights.get(line.page, 842.0))
        ]
        if not region:
            continue
        slices.append(
            QuestionSlice(
                number=start.number,
                start=start,
                lines=region,
                page_start=region[0].page,
                page_end=region[-1].page,
            )
        )
    return slices
