from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from questbank.types.layout import BoundingBox
from questbank.types.question import (
    OPTION_LABELS,
    OptionLabel,
    ParsedQuestion,
    SourceRegion,
    ValidationIssue,
)

PaperType = Literal["mcq", "structured"]
DocumentRole = Literal["question_paper", "answer_document", "syllabus"]
StageStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]
CheckStatus = Literal["passed", "failed", "needs_review", "not_evaluated"]
EvalSectionId = Literal[
    "segmentation",
    "option_table_fidelity",
    "notation",
    "visuals",
    "answer_alignment",
    "syllabus_classification",
    "explanation_correctness",
]


class PaperIdentity(BaseModel):
    """Stable identity for matching questions to answers (not syllabus version)."""

    source_exam_year: int = Field(serialization_alias="sourceExamYear")
    paper_code: str = Field(serialization_alias="paperCode")
    paper_type: PaperType = Field(default="mcq", serialization_alias="paperType")

    model_config = {"populate_by_name": True}

    def identity_key(self) -> str:
        return f"{self.source_exam_year}|{self.paper_code}|{self.paper_type}"

    def source_key_for(self, question_ref: str) -> str:
        return f"{self.identity_key()}|{normalize_question_ref(question_ref)}"


class AnswerSourceEvidence(BaseModel):
    page: int
    bounding_box: BoundingBox | None = Field(default=None, serialization_alias="boundingBox")
    text_snippet: str | None = Field(default=None, serialization_alias="textSnippet")

    model_config = {"populate_by_name": True}


class AnswerKeyEntry(BaseModel):
    paper_identity: PaperIdentity = Field(serialization_alias="paperIdentity")
    question_ref: str = Field(serialization_alias="questionRef")
    correct_option: OptionLabel = Field(serialization_alias="correctOption")
    source_evidence: AnswerSourceEvidence = Field(serialization_alias="sourceEvidence")
    origin: str

    model_config = {"populate_by_name": True}


class TopicClassification(BaseModel):
    """Syllabus topic assignment for a single MCQ (Milestone 2)."""

    topic: str | None = None
    parent_topic: str | None = Field(default=None, serialization_alias="parentTopic")
    subject: str = "Chemistry"
    syllabus_code: str | None = Field(default=None, serialization_alias="syllabusCode")
    topic_confidence: float | None = Field(default=None, serialization_alias="topicConfidence")
    topic_match_reasoning: str | None = Field(
        default=None,
        serialization_alias="topicMatchReasoning",
    )
    topic_match_method: str | None = Field(
        default=None,
        serialization_alias="topicMatchMethod",
    )
    status: str = "ok"  # ok | needs_review

    model_config = {"populate_by_name": True}


class QuestionRecord(BaseModel):
    """Parsed MCQ plus ingest identity / multi-region source metadata."""

    paper_identity: PaperIdentity = Field(serialization_alias="paperIdentity")
    source_key: str = Field(serialization_alias="sourceKey")
    question_ref: str = Field(serialization_alias="questionRef")
    source_regions: list[SourceRegion] = Field(
        default_factory=list,
        serialization_alias="sourceRegions",
    )
    question: ParsedQuestion

    # Joined from answer key via match_questions_and_answers — never invent letters.
    correct_option: OptionLabel | None = Field(
        default=None,
        serialization_alias="correctOption",
    )
    answer_source: AnswerSourceEvidence | None = Field(
        default=None,
        serialization_alias="answerSource",
    )

    topic_classification: TopicClassification | None = Field(
        default=None,
        serialization_alias="topicClassification",
    )

    # Explicitly unset review / scientific gates for Milestone 1.
    scientific_correctness: bool | None = Field(
        default=None,
        serialization_alias="scientificCorrectness",
    )
    review_status: str | None = Field(default=None, serialization_alias="reviewStatus")

    model_config = {"populate_by_name": True}


class DocumentDescriptor(BaseModel):
    role: DocumentRole
    path: str
    sha256: str | None = None
    page_count: int | None = Field(default=None, serialization_alias="pageCount")
    notes: str | None = None
    ignored_sections: list[str] = Field(
        default_factory=list,
        serialization_alias="ignoredSections",
    )

    model_config = {"populate_by_name": True}


class StageResult(BaseModel):
    name: str
    status: StageStatus
    message: str | None = None
    started_at: str | None = Field(default=None, serialization_alias="startedAt")
    finished_at: str | None = Field(default=None, serialization_alias="finishedAt")
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class DocumentManifest(BaseModel):
    run_id: str = Field(serialization_alias="runId")
    paper_identity: PaperIdentity = Field(serialization_alias="paperIdentity")
    expected_question_count: int = Field(serialization_alias="expectedQuestionCount")
    documents: list[DocumentDescriptor] = Field(default_factory=list)
    stages: list[StageResult] = Field(default_factory=list)
    parser_versions: dict[str, str] = Field(
        default_factory=dict,
        serialization_alias="parserVersions",
    )
    missing_inputs: list[str] = Field(
        default_factory=list,
        serialization_alias="missingInputs",
    )

    model_config = {"populate_by_name": True}


class MatchingReport(BaseModel):
    paper_identity: PaperIdentity = Field(serialization_alias="paperIdentity")
    matched: list[str] = Field(default_factory=list)
    unmatched_questions: list[str] = Field(
        default_factory=list,
        serialization_alias="unmatchedQuestions",
    )
    unused_answers: list[str] = Field(
        default_factory=list,
        serialization_alias="unusedAnswers",
    )
    duplicate_question_refs: list[str] = Field(
        default_factory=list,
        serialization_alias="duplicateQuestionRefs",
    )
    duplicate_answer_refs: list[str] = Field(
        default_factory=list,
        serialization_alias="duplicateAnswerRefs",
    )

    model_config = {"populate_by_name": True}


class EvaluationAxis(BaseModel):
    """Separate honesty axes — never collapse into a single accuracy %."""

    schema_validity: CheckStatus = Field(serialization_alias="schemaValidity")
    source_fidelity: CheckStatus = Field(serialization_alias="sourceFidelity")
    answer_alignment: CheckStatus = Field(serialization_alias="answerAlignment")

    model_config = {"populate_by_name": True}


class EvaluationCheck(BaseModel):
    code: str
    status: CheckStatus
    message: str
    question_ref: str | None = Field(default=None, serialization_alias="questionRef")
    evidence: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class EvaluationSection(BaseModel):
    id: EvalSectionId
    title: str
    status: CheckStatus
    checks: list[EvaluationCheck] = Field(default_factory=list)
    notes: str | None = None

    model_config = {"populate_by_name": True}


class EvaluationReport(BaseModel):
    paper_identity: PaperIdentity = Field(serialization_alias="paperIdentity")
    run_id: str = Field(serialization_alias="runId")
    axes: EvaluationAxis
    sections: list[EvaluationSection] = Field(default_factory=list)
    regression_cases: list[EvaluationCheck] = Field(
        default_factory=list,
        serialization_alias="regressionCases",
    )
    paper_issues: list[ValidationIssue] = Field(
        default_factory=list,
        serialization_alias="paperIssues",
    )

    model_config = {"populate_by_name": True}


def normalize_question_ref(value: str | int) -> str:
    text = str(value).strip().upper()
    if text.startswith("Q"):
        text = text[1:].lstrip()
    text = text.lstrip("0") or "0"
    if text.isdigit():
        return f"Q{int(text)}"
    return f"Q{text}"


def question_ref_from_number(number: int) -> str:
    return f"Q{number}"


__all__ = [
    "OPTION_LABELS",
    "AnswerKeyEntry",
    "AnswerSourceEvidence",
    "CheckStatus",
    "DocumentDescriptor",
    "DocumentManifest",
    "EvalSectionId",
    "EvaluationAxis",
    "EvaluationCheck",
    "EvaluationReport",
    "EvaluationSection",
    "MatchingReport",
    "PaperIdentity",
    "QuestionRecord",
    "StageResult",
    "TopicClassification",
    "normalize_question_ref",
    "question_ref_from_number",
]
