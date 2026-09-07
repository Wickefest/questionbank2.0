from __future__ import annotations

from collections import Counter

from questbank.types.question import (
    OPTION_LABELS,
    OptionLabel,
    PaperValidation,
    ParsedPaper,
    ParsedQuestion,
    QuestionValidation,
    ValidationIssue,
)


def validate_parsed_paper(
    questions: list[ParsedQuestion],
    expected_count: int = 40,
) -> ParsedPaper:
    numbered = sorted(questions, key=lambda item: item.question_number)
    counts = Counter(item.question_number for item in numbered)
    expected_numbers = list(range(1, expected_count + 1))
    missing = [number for number in expected_numbers if number not in counts]
    duplicates = [number for number, count in counts.items() if count > 1]

    paper_issues: list[ValidationIssue] = []
    if missing:
        paper_issues.append(
            ValidationIssue(
                code="MISSING_QUESTION",
                message=f"Missing question numbers: {missing}",
                severity="error",
            )
        )
    if duplicates:
        paper_issues.append(
            ValidationIssue(
                code="DUPLICATE_QUESTION",
                message=f"Duplicate question numbers: {duplicates}",
                severity="error",
            )
        )
    if len(numbered) != expected_count:
        paper_issues.append(
            ValidationIssue(
                code="QUESTION_COUNT_MISMATCH",
                message=f"Detected {len(numbered)} questions; expected {expected_count}",
                severity="error",
            )
        )

    validated: list[ParsedQuestion] = []
    for question in numbered:
        validated.append(_validate_question(question))

    pass_count = sum(1 for question in validated if question.validation.status == "pass")
    review_count = sum(1 for question in validated if question.validation.status == "review")
    visual_required = [
        question.question_number for question in validated if question.visual.required
    ]
    return ParsedPaper(
        questions=validated,
        validation=PaperValidation(
            questions_expected=expected_count,
            questions_detected=len(validated),
            missing_questions=missing,
            duplicate_questions=duplicates,
            pass_count=pass_count,
            review_count=review_count,
            visual_required_questions=visual_required,
            issues=paper_issues,
        ),
    )


def option_is_evidenced(question: ParsedQuestion, label: OptionLabel) -> bool:
    """True when option has extractable text and/or a visual crop asset."""
    option = question.options.get(label)
    if option is None:
        return False
    if option.text is not None and option.text.strip():
        return True
    return question_has_option_visual_asset(question, label)


def question_has_option_visual_asset(
    question: ParsedQuestion,
    label: OptionLabel | None = None,
) -> bool:
    """True when an options-role crop exists (shared grid or per-label)."""
    for asset in question.visual.assets:
        if asset.role != "option":
            continue
        if label is None or asset.option_label is None or asset.option_label == label:
            return True
    return False


def _validate_question(question: ParsedQuestion) -> ParsedQuestion:
    issues: list[ValidationIssue] = []
    # Preserve multi-region list when callers only set `source`.
    if not question.source_regions:
        question = question.model_copy(update={"source_regions": [question.source]})

    if not question.stem.strip():
        issues.append(
            ValidationIssue(
                code="EMPTY_STEM",
                message="Question stem is empty",
                severity="error",
            )
        )
    for label in OPTION_LABELS:
        option = question.options.get(label)
        if option is None:
            issues.append(
                ValidationIssue(
                    code="MISSING_OPTION",
                    message=f"Option {label} is missing",
                    severity="error",
                )
            )
            continue
        if option.requires_visual:
            # Only pending when no option crop asset exists yet.
            if question_has_option_visual_asset(question, label):
                continue
            issues.append(
                ValidationIssue(
                    code="VISUAL_OPTION_EXTRACTION_PENDING",
                    message=f"Option {label} is visual and was not extracted",
                    severity="warning",
                )
            )
            continue
        if option.text is None or not option.text.strip():
            issues.append(
                ValidationIssue(
                    code="MISSING_OPTION_TEXT",
                    message=f"Option {label} has no extractable text",
                    severity="error",
                )
            )
    if question.visual.required:
        if question.visual.assets:
            pass
        else:
            issues.append(
                ValidationIssue(
                    code="VISUAL_EXTRACTION_PENDING",
                    message="Question appears to require a diagram, graph, or apparatus image",
                    severity="warning",
                )
            )
    if question.source.bounding_box is None:
        issues.append(
            ValidationIssue(
                code="MISSING_BOUNDING_BOX",
                message="Question bounding region was not preserved",
                severity="warning",
            )
        )

    has_error = any(issue.severity == "error" for issue in issues)
    status = "review" if has_error else "pass"

    return question.model_copy(
        update={"validation": QuestionValidation(status=status, issues=issues)}
    )
