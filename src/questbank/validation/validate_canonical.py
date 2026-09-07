"""Deterministic validation for canonical MCQ ingest records."""

from __future__ import annotations

from pathlib import Path

from questbank.types.canonical import (
    OPTION_LABELS,
    CompleteQuestionRecord,
    CompositeVisualOptions,
    ImageBlock,
    MathOptions,
    MixedOptions,
    ParsedAnswer,
    ParsedQuestion,
    TableOptions,
    TextOptions,
    ValidationIssue,
    ValidationReport,
)
from questbank.types.ingest import MatchingReport


def option_labels(options) -> list[str]:
    if isinstance(options, CompositeVisualOptions):
        return [str(x) for x in options.labels]
    if isinstance(options, TableOptions):
        return [str(row.label) for row in options.rows]
    if isinstance(options, (TextOptions, MathOptions, MixedOptions)):
        return [str(item.label) for item in options.items]
    return []


def validate_canonical_ingest(
    *,
    questions: list[ParsedQuestion],
    answers: list[ParsedAnswer],
    records: list[CompleteQuestionRecord],
    matching: MatchingReport,
    assets_dir: str | Path | None = None,
    expected_question_count: int | None = None,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    needs_review: list[str] = []
    assets = Path(assets_dir) if assets_dir else None

    refs = [q.question_ref for q in questions]
    if len(refs) != len(set(refs)):
        dupes = sorted({r for r in refs if refs.count(r) > 1})
        issues.append(
            ValidationIssue(
                code="DUPLICATE_QUESTION_REFS",
                message=f"Duplicate question refs: {dupes}",
                severity="error",
            )
        )

    answer_refs = [a.question_ref for a in answers]
    if len(answer_refs) != len(set(answer_refs)):
        dupes = sorted({r for r in answer_refs if answer_refs.count(r) > 1})
        issues.append(
            ValidationIssue(
                code="DUPLICATE_ANSWER_REFS",
                message=f"Duplicate answer refs: {dupes}",
                severity="error",
            )
        )

    for q in questions:
        q_issues = _validate_question(q, assets_dir=assets)
        issues.extend(q_issues)
        if q.requires_review or any(i.severity == "error" for i in q_issues):
            needs_review.append(q.question_ref)

    for report_ref in matching.unmatched_questions:
        issues.append(
            ValidationIssue(
                code="UNMATCHED_QUESTION",
                message=f"No answer for question {report_ref}",
                severity="error",
                question_ref=_strip_q(report_ref),
            )
        )
        needs_review.append(_strip_q(report_ref))

    for report_ref in matching.unused_answers:
        issues.append(
            ValidationIssue(
                code="UNUSED_ANSWER",
                message=f"Unused answer ref {report_ref}",
                severity="error",
                question_ref=_strip_q(report_ref),
            )
        )

    for record in records:
        if record.answer is None:
            issues.append(
                ValidationIssue(
                    code="MISSING_ANSWER",
                    message=f"Record {record.question_ref} has no answer",
                    severity="error",
                    question_ref=record.question_ref,
                )
            )
            needs_review.append(record.question_ref)
            continue
        labels = option_labels(record.options)
        if record.answer.value not in labels and labels:
            issues.append(
                ValidationIssue(
                    code="ANSWER_NOT_IN_OPTIONS",
                    message=(
                        f"Answer {record.answer.value} not in option labels {labels} "
                        f"for {record.question_ref}"
                    ),
                    severity="error",
                    question_ref=record.question_ref,
                )
            )
            needs_review.append(record.question_ref)

    if expected_question_count is not None:
        if len(questions) != expected_question_count:
            issues.append(
                ValidationIssue(
                    code="QUESTION_COUNT_MISMATCH",
                    message=(
                        f"Expected {expected_question_count} questions, "
                        f"detected {len(questions)}"
                    ),
                    severity="error",
                )
            )

    errors = [i for i in issues if i.severity == "error"]
    return ValidationReport(
        ok=len(errors) == 0,
        questions_expected=expected_question_count,
        questions_detected=len(questions),
        answers_detected=len(answers),
        matched=len(matching.matched),
        issues=issues,
        needs_review_refs=sorted(set(needs_review), key=_ref_key),
    )


def _validate_question(q: ParsedQuestion, *, assets_dir: Path | None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not q.question_ref:
        issues.append(
            ValidationIssue(
                code="MISSING_REF",
                message="Question missing question_ref",
                severity="error",
            )
        )

    labels = option_labels(q.options)
    if not labels:
        issues.append(
            ValidationIssue(
                code="MISSING_OPTIONS",
                message=f"Question {q.question_ref} has no options",
                severity="error",
                question_ref=q.question_ref,
            )
        )
    elif len(labels) != len(set(labels)):
        issues.append(
            ValidationIssue(
                code="DUPLICATE_OPTION_LABELS",
                message=f"Question {q.question_ref} has duplicate option labels",
                severity="error",
                question_ref=q.question_ref,
            )
        )
    else:
        expected = list(OPTION_LABELS)
        if sorted(labels) != sorted(expected) and set(labels) != set(expected):
            # Allow if exactly A-D in some order
            if set(labels) != set(expected):
                issues.append(
                    ValidationIssue(
                        code="INCOMPLETE_OPTIONS",
                        message=f"Question {q.question_ref} options {labels} are not A-D",
                        severity="error",
                        question_ref=q.question_ref,
                    )
                )

    if isinstance(q.options, TableOptions):
        ncol = len(q.options.columns)
        for row in q.options.rows:
            if ncol and len(row.cells) != ncol:
                issues.append(
                    ValidationIssue(
                        code="TABLE_OPTION_COLUMN_MISMATCH",
                        message=(
                            f"Question {q.question_ref} option {row.label} has "
                            f"{len(row.cells)} cells, expected {ncol}"
                        ),
                        severity="error",
                        question_ref=q.question_ref,
                    )
                )
            if not row.cells:
                issues.append(
                    ValidationIssue(
                        code="TABLE_OPTION_EMPTY_ROW",
                        message=f"Question {q.question_ref} option {row.label} has empty cells",
                        severity="error",
                        question_ref=q.question_ref,
                    )
                )

    if isinstance(q.options, CompositeVisualOptions):
        if not q.options.asset:
            issues.append(
                ValidationIssue(
                    code="MISSING_COMPOSITE_ASSET",
                    message=f"Question {q.question_ref} composite_visual missing asset",
                    severity="error",
                    question_ref=q.question_ref,
                )
            )
        elif assets_dir is not None and not (assets_dir / q.options.asset).exists():
            issues.append(
                ValidationIssue(
                    code="MISSING_ASSET_FILE",
                    message=f"Missing asset file {q.options.asset}",
                    severity="error",
                    question_ref=q.question_ref,
                )
            )

    for block in q.content:
        if isinstance(block, ImageBlock):
            if not block.asset:
                issues.append(
                    ValidationIssue(
                        code="EMPTY_IMAGE_BLOCK",
                        message=f"Question {q.question_ref} has image block without asset",
                        severity="error",
                        question_ref=q.question_ref,
                    )
                )
            elif assets_dir is not None and not (assets_dir / block.asset).exists():
                issues.append(
                    ValidationIssue(
                        code="MISSING_ASSET_FILE",
                        message=f"Missing asset file {block.asset}",
                        severity="error",
                        question_ref=q.question_ref,
                    )
                )

    return issues


def _strip_q(ref: str) -> str:
    text = str(ref).strip()
    if text.upper().startswith("Q"):
        text = text[1:]
    return text.lstrip("0") or "0" if text.isdigit() or text.lstrip("0").isdigit() else text


def _ref_key(ref: str) -> tuple:
    if ref.isdigit():
        return (0, int(ref))
    return (1, ref)


__all__ = ["option_labels", "validate_canonical_ingest"]
