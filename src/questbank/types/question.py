from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from questbank.normalize.chemistry import ChemistryAnnotations
from questbank.types.layout import BoundingBox

OptionLabel = Literal["A", "B", "C", "D"]
ValidationStatus = Literal["pass", "review"]
OPTION_LABELS: tuple[OptionLabel, ...] = ("A", "B", "C", "D")


class ValidationIssue(BaseModel):
    code: str
    message: str
    severity: Literal["warning", "error"]


class ParsedOption(BaseModel):
    label: OptionLabel
    text: str | None
    requires_visual: bool = Field(serialization_alias="requiresVisual")


class SourceRegion(BaseModel):
    page_start: int = Field(serialization_alias="pageStart")
    page_end: int = Field(serialization_alias="pageEnd")
    bounding_box: BoundingBox | None = Field(default=None, serialization_alias="boundingBox")


class VisualAsset(BaseModel):
    role: Literal["stem", "option"]
    option_label: OptionLabel | None = Field(default=None, serialization_alias="optionLabel")
    page: int
    bounding_box: BoundingBox = Field(serialization_alias="boundingBox")
    path: str
    mime_type: str = Field(default="image/png", serialization_alias="mimeType")


class VisualExpectation(BaseModel):
    required: bool
    extraction_pending: bool = Field(serialization_alias="extractionPending")
    assets: list[VisualAsset] = Field(default_factory=list)


TableRole = Literal["stem", "options"]


class ParsedTable(BaseModel):
    role: TableRole
    page: int
    bounding_box: BoundingBox = Field(serialization_alias="boundingBox")
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class QuestionValidation(BaseModel):
    status: ValidationStatus
    issues: list[ValidationIssue] = Field(default_factory=list)


class ParsedQuestion(BaseModel):
    question_number: int = Field(serialization_alias="questionNumber")
    source: SourceRegion
    stem: str
    question_type: Literal["mcq"] = Field(default="mcq", serialization_alias="questionType")
    options: dict[OptionLabel, ParsedOption]
    tables: list[ParsedTable] = Field(default_factory=list)
    chemistry: ChemistryAnnotations = Field(default_factory=ChemistryAnnotations)
    visual: VisualExpectation
    validation: QuestionValidation

    model_config = {"populate_by_name": True}


class PaperValidation(BaseModel):
    questions_expected: int = 40
    questions_detected: int = 0
    missing_questions: list[int] = Field(default_factory=list)
    duplicate_questions: list[int] = Field(default_factory=list)
    pass_count: int = 0
    review_count: int = 0
    visual_required_questions: list[int] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)


class ParsedPaper(BaseModel):
    questions: list[ParsedQuestion] = Field(default_factory=list)
    validation: PaperValidation = Field(default_factory=PaperValidation)

    model_config = {"populate_by_name": True}
