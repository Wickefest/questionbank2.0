from __future__ import annotations

from questbank.types.question import ParsedPaper, ParsedQuestion


def format_parse_report(paper: ParsedPaper) -> str:
    validation = paper.validation
    refs = ", ".join(str(question.question_number) for question in paper.questions)
    missing = validation.missing_questions
    duplicates = validation.duplicate_questions
    lines = [
        "CHEMISTRY PAPER 1 PARSE REPORT",
        "",
        f"Questions expected: {validation.questions_expected}",
        f"Questions detected: {validation.questions_detected}",
        "",
        "Missing:",
        str(missing),
        "",
        "Duplicates:",
        str(duplicates),
        "",
        "Question refs:",
        refs,
        "",
        f"PASS: {validation.pass_count}",
        f"REVIEW: {validation.review_count}",
        "",
        "Visual-required questions:",
        str(validation.visual_required_questions),
        "",
    ]
    for question in paper.questions:
        lines.extend(_format_question(question))
        lines.append("")
        lines.append("--------------------------------")
        lines.append("")
    if lines[-1] == "" and len(lines) >= 2 and lines[-2] == "--------------------------------":
        lines = lines[:-2]
    return "\n".join(lines).rstrip() + "\n"


def _format_question(question: ParsedQuestion) -> list[str]:
    page = question.source.page_start
    stem = _preview(question.stem)
    lines = [
        f"Q{question.question_number}",
        f"Page: {page}",
        f"Stem: {stem}",
    ]
    for label in ("A", "B", "C", "D"):
        option = question.options.get(label)
        if option is None:
            lines.append(f"{label}: <missing>")
        elif option.requires_visual:
            lines.append(f"{label}: <visual>")
        elif option.text:
            lines.append(f"{label}: {_preview(option.text)}")
        else:
            lines.append(f"{label}: <empty>")
    lines.append(f"Visual required: {str(question.visual.required).lower()}")
    if question.tables:
        roles = ", ".join(f"{table.role} {len(table.rows)}x{len(table.headers)}" for table in question.tables)
        lines.append(f"Tables: {roles}")
    lines.append(f"Status: {question.validation.status.upper()}")
    return lines


def _preview(text: str, limit: int = 100) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3] + "..."
