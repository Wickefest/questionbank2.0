from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from questbank.types.layout import BoundingBox
from questbank.types.question import (
    ContentBlock,
    ParsedTable,
    QuestionValidation,
    SourceRegion,
    ValidationIssue,
    VisualExpectation,
)


class StructuredPart(BaseModel):
    label: str
    prompt: str
    marks: int | None = None
    children: list[StructuredPart] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class StructuredQuestion(BaseModel):
    question_number: int = Field(serialization_alias="questionNumber")
    source: SourceRegion
    question_type: Literal["structured"] = Field(
        default="structured", serialization_alias="questionType"
    )
    stem: str = ""
    parts: list[StructuredPart] = Field(default_factory=list)
    content: list[ContentBlock] = Field(default_factory=list)
    marks_total: int | None = Field(default=None, serialization_alias="marksTotal")
    tables: list[ParsedTable] = Field(default_factory=list)
    visual: VisualExpectation
    validation: QuestionValidation

    model_config = {"populate_by_name": True}


class StructuredPaperValidation(BaseModel):
    questions_expected: int | None = Field(default=None, serialization_alias="questionsExpected")
    questions_detected: int = Field(default=0, serialization_alias="questionsDetected")
    answers_section_page: int | None = Field(
        default=None, serialization_alias="answersSectionPage"
    )
    used_ocr: bool = Field(default=False, serialization_alias="usedOcr")
    used_vision: bool = Field(default=False, serialization_alias="usedVision")
    issues: list[ValidationIssue] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class StructuredPaper(BaseModel):
    title: str | None = None
    questions: list[StructuredQuestion] = Field(default_factory=list)
    validation: StructuredPaperValidation = Field(default_factory=StructuredPaperValidation)

    model_config = {"populate_by_name": True}
