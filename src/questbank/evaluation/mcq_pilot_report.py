from __future__ import annotations

from collections import Counter

from questbank.types.ingest import (
    AnswerKeyEntry,
    CheckStatus,
    EvaluationAxis,
    EvaluationCheck,
    EvaluationReport,
    EvaluationSection,
    MatchingReport,
    PaperIdentity,
    QuestionRecord,
    normalize_question_ref,
)
from questbank.types.question import OPTION_LABELS, PaperValidation, ParsedQuestion
from questbank.validation.validate_parsed_paper import (
    option_is_evidenced,
    question_has_option_visual_asset,
)

# Regression focus questions from the Milestone 1 plan.
_REGRESSION_REFS = ("Q1", "Q2", "Q4", "Q7", "Q8", "Q29", "Q32", "Q38", "Q40")


def build_evaluation_report(
    *,
    run_id: str,
    paper_identity: PaperIdentity,
    records: list[QuestionRecord],
    answers: list[AnswerKeyEntry],
    matching: MatchingReport,
    paper_validation: PaperValidation,
    expected_count: int,
) -> EvaluationReport:
    questions = [r.question for r in records]
    by_ref = {normalize_question_ref(r.question_ref): r for r in records}

    seg_checks = _segmentation_checks(paper_validation, expected_count, matching)
    opt_checks = _option_fidelity_checks(questions)
    notation_checks = _notation_checks(questions)
    visual_checks = _visual_checks(questions)
    answer_checks = _answer_alignment_checks(matching, answers, expected_count, records)
    syllabus_checks = _syllabus_classification_checks(records)

    sections = [
        EvaluationSection(
            id="segmentation",
            title="1. Question / segmentation integrity",
            status=_section_status(seg_checks),
            checks=seg_checks,
        ),
        EvaluationSection(
            id="option_table_fidelity",
            title="2. Option / table fidelity",
            status=_section_status(opt_checks),
            checks=opt_checks,
        ),
        EvaluationSection(
            id="notation",
            title="3. Chemistry notation fidelity",
            status=_section_status(notation_checks),
            checks=notation_checks,
        ),
        EvaluationSection(
            id="visuals",
            title="4. Visual / crop integrity",
            status=_section_status(visual_checks),
            checks=visual_checks,
        ),
        EvaluationSection(
            id="answer_alignment",
            title="5. Answer-key extraction and alignment",
            status=_section_status(answer_checks),
            checks=answer_checks,
        ),
        EvaluationSection(
            id="syllabus_classification",
            title="6. Syllabus classification",
            status=_section_status(syllabus_checks),
            checks=syllabus_checks,
            notes=None if syllabus_checks else "No syllabus classifications present",
        ),
        EvaluationSection(
            id="explanation_correctness",
            title="7. Explanation correctness",
            status="not_evaluated",
            checks=[],
            notes="Deferred to Milestone 3",
        ),
    ]

    regression = _regression_case_checks(by_ref)

    schema_validity = _axis_from_checks(seg_checks + opt_checks)
    source_fidelity = _axis_from_checks(opt_checks + notation_checks + visual_checks)
    answer_alignment = _axis_from_checks(answer_checks)

    return EvaluationReport(
        paper_identity=paper_identity,
        run_id=run_id,
        axes=EvaluationAxis(
            schema_validity=schema_validity,
            source_fidelity=source_fidelity,
            answer_alignment=answer_alignment,
        ),
        sections=sections,
        regression_cases=regression,
        paper_issues=list(paper_validation.issues),
    )


def _segmentation_checks(
    validation: PaperValidation,
    expected_count: int,
    matching: MatchingReport,
) -> list[EvaluationCheck]:
    checks: list[EvaluationCheck] = []
    if validation.missing_questions:
        checks.append(
            EvaluationCheck(
                code="MISSING_QUESTION_REFS",
                status="failed",
                message=f"Missing question numbers: {validation.missing_questions}",
            )
        )
    else:
        checks.append(
            EvaluationCheck(
                code="MISSING_QUESTION_REFS",
                status="passed",
                message="No missing question numbers in expected range",
            )
        )
    if validation.duplicate_questions or matching.duplicate_question_refs:
        checks.append(
            EvaluationCheck(
                code="DUPLICATE_QUESTION_REFS",
                status="failed",
                message=(
                    f"duplicates paper={validation.duplicate_questions} "
                    f"matching={matching.duplicate_question_refs}"
                ),
            )
        )
    else:
        checks.append(
            EvaluationCheck(
                code="DUPLICATE_QUESTION_REFS",
                status="passed",
                message="No duplicate question refs",
            )
        )
    detected = validation.questions_detected
    if detected != expected_count:
        checks.append(
            EvaluationCheck(
                code="QUESTION_COUNT",
                status="failed",
                message=f"Detected {detected}, expected {expected_count}",
            )
        )
    else:
        checks.append(
            EvaluationCheck(
                code="QUESTION_COUNT",
                status="passed",
                message=f"Detected {detected} questions (fixture expected_count={expected_count})",
            )
        )
    if matching.unmatched_questions:
        checks.append(
            EvaluationCheck(
                code="UNMATCHED_QUESTIONS",
                status="needs_review" if matching.matched else "failed",
                message=f"Unmatched questions: {matching.unmatched_questions}",
            )
        )
    else:
        checks.append(
            EvaluationCheck(
                code="UNMATCHED_QUESTIONS",
                status="passed",
                message="All questions matched an answer in the selected key section",
            )
        )
    return checks


def _option_fidelity_checks(questions: list[ParsedQuestion]) -> list[EvaluationCheck]:
    checks: list[EvaluationCheck] = []
    unevidenced = 0
    for question in questions:
        missing = [
            label
            for label in OPTION_LABELS
            if not option_is_evidenced(question, label)
        ]
        if missing:
            unevidenced += 1
            checks.append(
                EvaluationCheck(
                    code="UNEVIDENCED_OPTIONS",
                    status="failed",
                    message=f"Q{question.question_number} missing evidenced choices: {missing}",
                    question_ref=f"Q{question.question_number}",
                )
            )
    if unevidenced == 0:
        checks.append(
            EvaluationCheck(
                code="UNEVIDENCED_OPTIONS",
                status="passed",
                message="Every MCQ has four evidenced choices (text and/or visual asset)",
            )
        )
    # Soft flag: suspicious identical option text
    for question in questions:
        texts = [
            (question.options[label].text or "").strip().lower()
            for label in OPTION_LABELS
            if not question.options[label].requires_visual
            and (question.options[label].text or "").strip()
        ]
        if len(texts) >= 2 and len(set(texts)) == 1:
            checks.append(
                EvaluationCheck(
                    code="SUSPICIOUS_DUPLICATE_OPTION_TEXT",
                    status="needs_review",
                    message=f"Q{question.question_number} all text options identical",
                    question_ref=f"Q{question.question_number}",
                )
            )
    return checks


def _notation_checks(questions: list[ParsedQuestion]) -> list[EvaluationCheck]:
    checks: list[EvaluationCheck] = []
    spaced = 0
    for question in questions:
        blob = " ".join(
            [
                question.stem,
                *[
                    (question.options[label].text or "")
                    for label in OPTION_LABELS
                ],
            ]
        )
        # Common OCR bleed: element + space + digit (CH 4, CO 2, H 2 O)
        if _has_spaced_formula(blob):
            spaced += 1
            checks.append(
                EvaluationCheck(
                    code="SPACED_FORMULA_DIGITS",
                    status="needs_review",
                    message=f"Q{question.question_number} may have spaced formula digits",
                    question_ref=f"Q{question.question_number}",
                )
            )
    if spaced == 0:
        checks.append(
            EvaluationCheck(
                code="SPACED_FORMULA_DIGITS",
                status="passed",
                message="No obvious spaced formula-digit patterns flagged",
            )
        )
    return checks


def _visual_checks(questions: list[ParsedQuestion]) -> list[EvaluationCheck]:
    checks: list[EvaluationCheck] = []
    missing_required = 0
    invalid_coords = 0
    for question in questions:
        if question.visual.required and not question.visual.assets:
            missing_required += 1
            checks.append(
                EvaluationCheck(
                    code="MISSING_REQUIRED_VISUAL",
                    status="needs_review",
                    message=f"Q{question.question_number} requires visual but has no assets",
                    question_ref=f"Q{question.question_number}",
                )
            )
        for asset in question.visual.assets:
            box = asset.bounding_box
            if box.x1 <= box.x0 or box.y1 <= box.y0:
                invalid_coords += 1
                checks.append(
                    EvaluationCheck(
                        code="INVALID_ASSET_COORDINATES",
                        status="failed",
                        message=f"Q{question.question_number} asset has invalid bbox",
                        question_ref=f"Q{question.question_number}",
                        evidence={"path": asset.path},
                    )
                )
        # False pending: requires_visual option but asset exists
        for label in OPTION_LABELS:
            option = question.options.get(label)
            if option and option.requires_visual and question_has_option_visual_asset(question):
                # OK — evidenced
                continue
            if option and option.requires_visual and not question_has_option_visual_asset(question):
                checks.append(
                    EvaluationCheck(
                        code="VISUAL_OPTION_PENDING",
                        status="needs_review",
                        message=f"Q{question.question_number} option {label} still pending crop",
                        question_ref=f"Q{question.question_number}",
                    )
                )
    if missing_required == 0 and invalid_coords == 0:
        checks.append(
            EvaluationCheck(
                code="VISUAL_INTEGRITY",
                status="passed",
                message="Required visuals present with valid coordinates (or none required)",
            )
        )
    return checks


def _answer_alignment_checks(
    matching: MatchingReport,
    answers: list[AnswerKeyEntry],
    expected_count: int,
    records: list[QuestionRecord] | None = None,
) -> list[EvaluationCheck]:
    checks: list[EvaluationCheck] = []
    if not answers:
        checks.append(
            EvaluationCheck(
                code="ANSWER_KEY_PRESENT",
                status="needs_review",
                message="No answers extracted (mark PDF missing or empty page-1 key)",
            )
        )
        return checks

    answer_refs = [normalize_question_ref(a.question_ref) for a in answers]
    counts = Counter(answer_refs)
    dupes = [ref for ref, count in counts.items() if count > 1]
    if dupes:
        checks.append(
            EvaluationCheck(
                code="DUPLICATE_ANSWER_REFS",
                status="failed",
                message=f"Duplicate answer refs in selected section: {dupes}",
            )
        )
    else:
        checks.append(
            EvaluationCheck(
                code="DUPLICATE_ANSWER_REFS",
                status="passed",
                message="No duplicate answer refs in selected key section",
            )
        )

    if matching.unused_answers:
        checks.append(
            EvaluationCheck(
                code="UNUSED_ANSWERS",
                status="needs_review",
                message=f"Unused answers in selected section: {matching.unused_answers}",
            )
        )
    else:
        checks.append(
            EvaluationCheck(
                code="UNUSED_ANSWERS",
                status="passed",
                message="No unused answers in the selected key section",
            )
        )

    if len(matching.matched) == expected_count and not matching.unmatched_questions:
        checks.append(
            EvaluationCheck(
                code="ANSWER_MATCH_COVERAGE",
                status="passed",
                message=f"Matched {len(matching.matched)}/{expected_count} on paper_identity+question_ref",
            )
        )
    else:
        checks.append(
            EvaluationCheck(
                code="ANSWER_MATCH_COVERAGE",
                status="needs_review",
                message=(
                    f"Matched {len(matching.matched)}/{expected_count}; "
                    f"unmatched={matching.unmatched_questions}"
                ),
            )
        )

    if records is not None:
        missing_join = [
            normalize_question_ref(r.question_ref)
            for r in records
            if normalize_question_ref(r.question_ref) in set(matching.matched)
            and r.correct_option is None
        ]
        if missing_join:
            checks.append(
                EvaluationCheck(
                    code="ANSWER_JOIN_COMPLETE",
                    status="failed",
                    message=f"Matched refs missing joined correct_option: {missing_join}",
                )
            )
        else:
            joined = sum(1 for r in records if r.correct_option is not None)
            checks.append(
                EvaluationCheck(
                    code="ANSWER_JOIN_COMPLETE",
                    status="passed",
                    message=f"Joined correct_option onto {joined} question records",
                )
            )
    return checks


def _syllabus_classification_checks(records: list[QuestionRecord]) -> list[EvaluationCheck]:
    checks: list[EvaluationCheck] = []
    if not records:
        return [
            EvaluationCheck(
                code="SYLLABUS_COVERAGE",
                status="not_evaluated",
                message="No question records",
            )
        ]

    tagged = [r for r in records if r.topic_classification is not None]
    if not tagged:
        return [
            EvaluationCheck(
                code="SYLLABUS_COVERAGE",
                status="not_evaluated",
                message="No syllabus classifications on records (stage skipped or failed)",
            )
        ]

    with_code = [r for r in tagged if r.topic_classification and r.topic_classification.syllabus_code]
    review = [
        r
        for r in tagged
        if r.topic_classification and r.topic_classification.status == "needs_review"
    ]
    if len(with_code) == len(records):
        checks.append(
            EvaluationCheck(
                code="SYLLABUS_COVERAGE",
                status="passed" if not review else "needs_review",
                message=(
                    f"Tagged {len(with_code)}/{len(records)} "
                    f"(needs_review={len(review)})"
                ),
            )
        )
    else:
        checks.append(
            EvaluationCheck(
                code="SYLLABUS_COVERAGE",
                status="needs_review",
                message=f"Tagged {len(with_code)}/{len(records)} with syllabus_code",
            )
        )
    return checks


def _regression_case_checks(by_ref: dict[str, QuestionRecord]) -> list[EvaluationCheck]:
    """Flag presence/structure for known hard questions — not a fake accuracy %."""
    checks: list[EvaluationCheck] = []
    for ref in _REGRESSION_REFS:
        record = by_ref.get(ref)
        if record is None:
            checks.append(
                EvaluationCheck(
                    code="REGRESSION_CASE",
                    status="failed",
                    message=f"{ref} missing from parsed questions",
                    question_ref=ref,
                )
            )
            continue
        question = record.question
        evidenced = all(option_is_evidenced(question, label) for label in OPTION_LABELS)
        has_stem = bool(question.stem.strip())
        status: CheckStatus = "passed" if evidenced and has_stem else "needs_review"
        checks.append(
            EvaluationCheck(
                code="REGRESSION_CASE",
                status=status,
                message=(
                    f"{ref} stem={'ok' if has_stem else 'empty'} "
                    f"evidenced_options={'ok' if evidenced else 'incomplete'} "
                    f"visual_assets={len(question.visual.assets)}"
                ),
                question_ref=ref,
                evidence={
                    "tables": len(question.tables),
                    "requires_visual": question.visual.required,
                },
            )
        )
    return checks


def _section_status(checks: list[EvaluationCheck]) -> CheckStatus:
    if not checks:
        return "not_evaluated"
    if any(c.status == "failed" for c in checks):
        return "failed"
    if any(c.status == "needs_review" for c in checks):
        return "needs_review"
    if all(c.status == "not_evaluated" for c in checks):
        return "not_evaluated"
    return "passed"


def _axis_from_checks(checks: list[EvaluationCheck]) -> CheckStatus:
    return _section_status(checks)


def _has_spaced_formula(text: str) -> bool:
    import re

    return bool(re.search(r"\b[A-Z][a-z]?\s+\d\b", text or ""))
