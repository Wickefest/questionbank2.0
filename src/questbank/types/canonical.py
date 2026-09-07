"""Lean canonical MCQ schemas for Docling + Gemini ingestion."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

OptionLabel = Literal["A", "B", "C", "D"]
OPTION_LABELS: tuple[OptionLabel, ...] = ("A", "B", "C", "D")

QuestionStatus = Literal["DRAFT", "NEEDS_REVIEW", "APPROVED", "PUBLISHED"]
ExplanationSource = Literal["mark_scheme"]


# ---------------------------------------------------------------------------
# Source metadata (admin / debug — not student-facing content)
# ---------------------------------------------------------------------------


class SourceRegion(BaseModel):
    page: int
    bbox: list[float] | None = None  # optional [ymin, xmin, ymax, xmax] 0-1000


class NormBBox(BaseModel):
    """Gemini-style normalized box on a 0–1000 scale: [ymin, xmin, ymax, xmax]."""

    ymin: float
    xmin: float
    ymax: float
    xmax: float

    @classmethod
    def from_list(cls, values: list[float] | tuple[float, ...]) -> NormBBox:
        if len(values) != 4:
            raise ValueError(f"Expected 4 bbox values, got {len(values)}")
        return cls(ymin=values[0], xmin=values[1], ymax=values[2], xmax=values[3])

    def as_list(self) -> list[float]:
        return [self.ymin, self.xmin, self.ymax, self.xmax]


# ---------------------------------------------------------------------------
# Content blocks (ordered; one representation for the frontend)
# ---------------------------------------------------------------------------


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    value: str


class MathBlock(BaseModel):
    type: Literal["math"] = "math"
    latex: str


class ChemistryBlock(BaseModel):
    type: Literal["chemistry"] = "chemistry"
    value: str


class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class ImageBlock(BaseModel):
    type: Literal["image"] = "image"
    asset: str
    bbox: list[float] | None = None  # source crop hint before asset written


class ListBlock(BaseModel):
    type: Literal["list"] = "list"
    items: list[str] = Field(default_factory=list)


ContentBlock = Annotated[
    TextBlock | MathBlock | ChemistryBlock | TableBlock | ImageBlock | ListBlock,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Option modes
# ---------------------------------------------------------------------------


class TextOptionItem(BaseModel):
    label: OptionLabel
    content: str


class MathOptionItem(BaseModel):
    label: OptionLabel
    latex: str


class TableOptionRow(BaseModel):
    label: OptionLabel
    cells: list[str]


class TextOptions(BaseModel):
    mode: Literal["text"] = "text"
    items: list[TextOptionItem]


class MathOptions(BaseModel):
    mode: Literal["math"] = "math"
    items: list[MathOptionItem]


class TableOptions(BaseModel):
    mode: Literal["table"] = "table"
    columns: list[str]
    rows: list[TableOptionRow]


class CompositeVisualOptions(BaseModel):
    mode: Literal["composite_visual"] = "composite_visual"
    labels: list[OptionLabel] = Field(default_factory=lambda: list(OPTION_LABELS))
    asset: str
    bbox: list[float] | None = None


class MixedOptionItem(BaseModel):
    label: OptionLabel
    content: str | None = None
    latex: str | None = None
    asset: str | None = None


class MixedOptions(BaseModel):
    mode: Literal["mixed"] = "mixed"
    items: list[MixedOptionItem]
    asset: str | None = None
    bbox: list[float] | None = None


QuestionOptions = Annotated[
    TextOptions | MathOptions | TableOptions | CompositeVisualOptions | MixedOptions,
    Field(discriminator="mode"),
]


# ---------------------------------------------------------------------------
# Parsed question / answer / complete record
# ---------------------------------------------------------------------------


class ParsedQuestion(BaseModel):
    question_ref: str
    question_type: Literal["mcq"] = "mcq"
    content: list[ContentBlock] = Field(default_factory=list)
    options: QuestionOptions
    source_page: int | None = None
    source_regions: list[SourceRegion] = Field(default_factory=list)
    requires_review: bool = False


class ParsedAnswer(BaseModel):
    question_ref: str
    answer: OptionLabel
    explanation: str | None = None


class AnswerPayload(BaseModel):
    value: OptionLabel
    explanation: str | None = None
    explanation_source: ExplanationSource | None = None


class CompleteQuestionRecord(BaseModel):
    question_ref: str
    question_type: Literal["mcq"] = "mcq"
    content: list[ContentBlock] = Field(default_factory=list)
    options: QuestionOptions
    answer: AnswerPayload | None = None
    classification: None = None
    status: QuestionStatus = "DRAFT"
    source_page: int | None = None
    source_regions: list[SourceRegion] = Field(default_factory=list)
    requires_review: bool = False


# ---------------------------------------------------------------------------
# Gemini structured-output envelopes (page-level)
# ---------------------------------------------------------------------------


class GeminiStemVisual(BaseModel):
    """A meaningful stem diagram/graph that must be cropped."""

    bbox: list[float]  # [ymin, xmin, ymax, xmax] 0-1000
    role: Literal["diagram", "graph", "apparatus", "structure", "other"] = "diagram"


class GeminiPageQuestion(BaseModel):
    """One question as returned by Gemini for a single page image."""

    question_ref: str
    content: list[ContentBlock] = Field(default_factory=list)
    options: QuestionOptions
    stem_visuals: list[GeminiStemVisual] = Field(default_factory=list)
    options_bbox: list[float] | None = None  # required when composite_visual / mixed crop
    requires_review: bool = False
    continues_on_next_page: bool = False


class GeminiPageParseResult(BaseModel):
    questions: list[GeminiPageQuestion] = Field(default_factory=list)


class GeminiAnswerPageResult(BaseModel):
    answers: list[ParsedAnswer] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    code: str
    message: str
    severity: Literal["warning", "error"] = "error"
    question_ref: str | None = None


class ValidationReport(BaseModel):
    ok: bool = True
    questions_expected: int | None = None
    questions_detected: int = 0
    answers_detected: int = 0
    matched: int = 0
    issues: list[ValidationIssue] = Field(default_factory=list)
    needs_review_refs: list[str] = Field(default_factory=list)


__all__ = [
    "OPTION_LABELS",
    "AnswerPayload",
    "ChemistryBlock",
    "CompleteQuestionRecord",
    "CompositeVisualOptions",
    "ContentBlock",
    "ExplanationSource",
    "GeminiAnswerPageResult",
    "GeminiPageParseResult",
    "GeminiPageQuestion",
    "GeminiStemVisual",
    "ImageBlock",
    "ListBlock",
    "MathBlock",
    "MathOptionItem",
    "MathOptions",
    "MixedOptionItem",
    "MixedOptions",
    "NormBBox",
    "OptionLabel",
    "ParsedAnswer",
    "ParsedQuestion",
    "QuestionOptions",
    "QuestionStatus",
    "SourceRegion",
    "TableBlock",
    "TableOptionRow",
    "TableOptions",
    "TextBlock",
    "TextOptionItem",
    "TextOptions",
    "ValidationIssue",
    "ValidationReport",
]
