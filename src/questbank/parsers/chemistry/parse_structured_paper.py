from __future__ import annotations

import re
from pathlib import Path

from questbank.parsers.chemistry.detect_structured_boundaries import (
    StructuredSlice,
    detect_structured_boundaries,
    find_answers_section_page,
)
from questbank.parsers.chemistry.visual_cues import stem_requires_visual
from questbank.pdf.extract_pdf_layout import LayoutBackend, extract_pdf_layout
from questbank.pdf.extract_visuals import (
    assign_images_to_questions,
    build_slice_bands,
)
from questbank.types.layout import BoundingBox, ImageRegion, PaperLayout, TextLine
from questbank.types.question import (
    ParsedTable,
    QuestionValidation,
    SourceRegion,
    ValidationIssue,
    VisualAsset,
    VisualExpectation,
)
from questbank.types.structured import (
    StructuredPaper,
    StructuredPaperValidation,
    StructuredPart,
    StructuredQuestion,
)

_PART_START = re.compile(
    r"^\(\s*([a-z]|[ivx]+)\s*\)(?:\s+(.*))?$",
    re.I,
)
_MARKS = re.compile(r"\[\s*(\d+)\s*\]")
_TOTAL_MARKS = re.compile(r"(?i)\[\s*total\s*:\s*(\d+)\s*\]")
_ANSWER_DOTS = re.compile(r"^\.{3,}$|^_{3,}$|^[\.\s]{6,}$")
_PAGE_ONLY = re.compile(r"^\d{1,3}$")


def parse_structured_paper(
    pdf_path: str | Path,
    *,
    layout: PaperLayout | None = None,
    backend: LayoutBackend = "auto",
    ocr: bool | None = True,
    extract_visuals: bool = False,
    visuals_dir: str | Path | None = None,
    expected_count: int | None = None,
) -> StructuredPaper:
    """Parse a structured (written) chemistry paper into Q + parts."""
    pdf_path = Path(pdf_path)
    paper_layout = layout or extract_pdf_layout(pdf_path, backend=backend, ocr=ocr)
    answers_page = find_answers_section_page(paper_layout)
    slices = detect_structured_boundaries(paper_layout, stop_at_answers=True)

    starts = [(item.number, item.page_start, item.start.line.y0) for item in slices]
    final_page = (
        (answers_page - 1)
        if answers_page
        else (paper_layout.page_count or (slices[-1].page_end if slices else 1))
    )
    bands = build_slice_bands(starts, final_page=max(final_page, 1)) if starts else []
    all_images = [image for page in paper_layout.pages for image in page.images]
    # Drop near-full-page scan backgrounds from visual assignment.
    usable_images = [
        image
        for image in all_images
        if not _is_full_page_scan(image, paper_layout)
    ]
    images_by_question = assign_images_to_questions(bands, usable_images) if bands else {}

    title = _paper_title(paper_layout)
    questions: list[StructuredQuestion] = []
    for item in slices:
        images = images_by_question.get(item.number, [])
        question = _parse_structured_slice(item, paper_layout, images)
        questions.append(question)
        images_by_question[item.number] = images

    if extract_visuals and questions:
        out_dir = Path(visuals_dir) if visuals_dir else Path("output") / "ammonia-visuals"
        if out_dir.exists():
            for stale in out_dir.glob("q*.png"):
                stale.unlink(missing_ok=True)
        questions = _extract_structured_visuals(
            pdf_path, questions, images_by_question, out_dir
        )

    issues: list[ValidationIssue] = []
    if expected_count is not None and len(questions) != expected_count:
        issues.append(
            ValidationIssue(
                code="QUESTION_COUNT_MISMATCH",
                message=f"Expected {expected_count} questions, detected {len(questions)}",
                severity="warning",
            )
        )
    if not questions:
        issues.append(
            ValidationIssue(
                code="NO_QUESTIONS",
                message="No structured questions detected",
                severity="error",
            )
        )

    used_ocr = any(page.used_ocr for page in paper_layout.pages)
    return StructuredPaper(
        title=title,
        questions=questions,
        validation=StructuredPaperValidation(
            questions_expected=expected_count,
            questions_detected=len(questions),
            answers_section_page=answers_page,
            used_ocr=used_ocr,
            used_vision=False,
            issues=issues,
        ),
    )


def _parse_structured_slice(
    item: StructuredSlice,
    layout: PaperLayout,
    images: list[ImageRegion],
) -> StructuredQuestion:
    tables = _tables_for_slice(item, layout)
    raw_lines = [
        line
        for line in item.lines
        if not _PAGE_ONLY.match(line.text.strip())
        and not _ANSWER_DOTS.match(line.text.strip())
    ]
    marks_total = None
    for line in reversed(raw_lines):
        total = _TOTAL_MARKS.search(line.text)
        if total:
            marks_total = int(total.group(1))
            break

    stem_parts: list[str] = []
    if item.start.stem_prefix:
        stem_parts.append(item.start.stem_prefix)

    part_starts: list[tuple[int, str, str]] = []
    for index, line in enumerate(raw_lines):
        if index == 0 and _same_identity(line, item.start.line):
            continue
        match = _PART_START.match(line.text.strip())
        if match:
            part_starts.append((index, match.group(1).lower(), (match.group(2) or "").strip()))

    if not part_starts:
        stem = _join_text(stem_parts + [line.text.strip() for line in raw_lines[1:]])
        stem = _strip_marks(stem)
        visual_required = stem_requires_visual(stem) or bool(images) or bool(tables)
        return StructuredQuestion(
            question_number=item.number,
            source=SourceRegion(
                page_start=item.page_start,
                page_end=item.page_end,
                bounding_box=_slice_bbox(item, images),
            ),
            stem=stem,
            parts=[],
            marks_total=marks_total,
            tables=tables,
            visual=VisualExpectation(
                required=visual_required,
                extraction_pending=visual_required,
            ),
            validation=_question_validation(stem, []),
        )

    first_part_index = part_starts[0][0]
    for line in raw_lines[1:first_part_index]:
        if _PART_START.match(line.text.strip()):
            break
        if _TOTAL_MARKS.search(line.text):
            continue
        stem_parts.append(line.text.strip())
    stem = _strip_marks(_join_text(stem_parts))

    flat_parts: list[StructuredPart] = []
    for p_index, (line_index, label, inline) in enumerate(part_starts):
        end = part_starts[p_index + 1][0] if p_index + 1 < len(part_starts) else len(raw_lines)
        chunk_lines = raw_lines[line_index:end]
        texts = [inline] if inline else []
        for line in chunk_lines[1:]:
            text = line.text.strip()
            if _TOTAL_MARKS.search(text):
                continue
            if _ANSWER_DOTS.match(text):
                continue
            texts.append(text)
        prompt = _strip_marks(_join_text(texts))
        marks = _first_marks(chunk_lines)
        flat_parts.append(StructuredPart(label=label, prompt=prompt, marks=marks))

    nested = _nest_parts(flat_parts)
    visual_required = (
        stem_requires_visual(stem)
        or any(stem_requires_visual(part.prompt) for part in flat_parts)
        or bool(images)
        or bool(tables)
    )
    return StructuredQuestion(
        question_number=item.number,
        source=SourceRegion(
            page_start=item.page_start,
            page_end=item.page_end,
            bounding_box=_slice_bbox(item, images),
        ),
        stem=stem,
        parts=nested,
        marks_total=marks_total,
        tables=tables,
        visual=VisualExpectation(
            required=visual_required,
            extraction_pending=visual_required,
        ),
        validation=_question_validation(stem, nested),
    )


def _nest_parts(parts: list[StructuredPart]) -> list[StructuredPart]:
    """Nest (i)/(ii) under the preceding lettered part when present."""
    rooted: list[StructuredPart] = []
    for part in parts:
        if part.label in {"i", "ii", "iii", "iv", "v"} and rooted:
            parent = rooted[-1]
            rooted[-1] = parent.model_copy(
                update={"children": [*parent.children, part]}
            )
        else:
            rooted.append(part)
    return rooted


def _tables_for_slice(item: StructuredSlice, layout: PaperLayout) -> list[ParsedTable]:
    tables: list[ParsedTable] = []
    y_start = item.start.line.y0
    for page in layout.pages:
        if page.page_number < item.page_start or page.page_number > item.page_end:
            continue
        for table in page.tables:
            if page.page_number == item.page_start and table.bbox.y1 < y_start - 8:
                continue
            if page.page_number == item.page_end:
                last_y = item.lines[-1].y1 if item.lines else 10_000
                if table.bbox.y0 > last_y + 40:
                    continue
            tables.append(
                ParsedTable(
                    role="stem",
                    page=table.page,
                    bounding_box=table.bbox,
                    headers=table.headers,
                    rows=table.rows,
                )
            )
    return tables


def _extract_structured_visuals(
    pdf_path: Path,
    questions: list[StructuredQuestion],
    images_by_question: dict[int, list[ImageRegion]],
    output_dir: Path,
) -> list[StructuredQuestion]:
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF is required for visual extraction") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    updated: list[StructuredQuestion] = []
    with pymupdf.open(pdf_path) as doc:
        for question in questions:
            images = _unique_images(images_by_question.get(question.question_number, []))
            assets: list[VisualAsset] = []
            for index, image in enumerate(images):
                suffix = "" if len(images) == 1 else f"-{index + 1}"
                path = output_dir / f"q{question.question_number:02d}-stem{suffix}.png"
                asset = _render_crop(doc, image, path)
                if asset:
                    assets.append(asset)
            visual = VisualExpectation(
                required=question.visual.required or bool(assets),
                extraction_pending=question.visual.required and not assets,
                assets=assets,
            )
            updated.append(question.model_copy(update={"visual": visual}))
    return updated


def _render_crop(doc, image: ImageRegion, path: Path) -> VisualAsset | None:
    import pymupdf

    page_index = image.page - 1
    if page_index < 0 or page_index >= doc.page_count:
        return None
    page = doc[page_index]
    rect = pymupdf.Rect(image.bbox.x0, image.bbox.y0, image.bbox.x1, image.bbox.y1) & page.rect
    if rect.is_empty or rect.width < 4 or rect.height < 4:
        return None
    try:
        pix = page.get_pixmap(clip=rect, matrix=pymupdf.Matrix(2, 2), alpha=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(path))
    except Exception:  # noqa: BLE001
        return None
    return VisualAsset(
        role="stem",
        option_label=None,
        page=image.page,
        bounding_box=image.bbox,
        path=str(path).replace("\\", "/"),
        mime_type="image/png",
    )


def _is_full_page_scan(image: ImageRegion, layout: PaperLayout) -> bool:
    page = next((p for p in layout.pages if p.page_number == image.page), None)
    if page is None:
        return False
    page_area = max(page.width * page.height, 1.0)
    return image.bbox.area() / page_area > 0.55


def _unique_images(images: list[ImageRegion]) -> list[ImageRegion]:
    unique: list[ImageRegion] = []
    for image in images:
        if any(_almost_same(image, other) for other in unique):
            continue
        unique.append(image)
    return unique


def _almost_same(left: ImageRegion, right: ImageRegion, tol: float = 6.0) -> bool:
    if left.page != right.page:
        return False
    return (
        abs(left.bbox.x0 - right.bbox.x0) <= tol
        and abs(left.bbox.y0 - right.bbox.y0) <= tol
        and abs(left.bbox.x1 - right.bbox.x1) <= tol
        and abs(left.bbox.y1 - right.bbox.y1) <= tol
    )


def _paper_title(layout: PaperLayout) -> str | None:
    pieces: list[str] = []
    for line in layout.lines_in_reading_order()[:12]:
        text = line.text.strip()
        if _PAGE_ONLY.match(text):
            continue
        if re.match(r"(?i)^q\s*\d", text):
            break
        pieces.append(text)
        if len(pieces) >= 3:
            break
    title = " ".join(pieces).strip()
    return title or None


def _question_validation(stem: str, parts: list[StructuredPart]) -> QuestionValidation:
    issues: list[ValidationIssue] = []
    if not stem.strip() and not parts:
        issues.append(
            ValidationIssue(
                code="EMPTY_QUESTION",
                message="Question has no stem or parts",
                severity="error",
            )
        )
    for part in parts:
        if not part.prompt.strip() and not part.children:
            issues.append(
                ValidationIssue(
                    code="EMPTY_PART",
                    message=f"Part ({part.label}) has no prompt text",
                    severity="warning",
                )
            )
        for child in part.children:
            if not child.prompt.strip():
                issues.append(
                    ValidationIssue(
                        code="EMPTY_PART",
                        message=f"Part ({part.label})({child.label}) has no prompt text",
                        severity="warning",
                    )
                )
    status = "review" if issues else "pass"
    return QuestionValidation(status=status, issues=issues)


def _slice_bbox(item: StructuredSlice, images: list[ImageRegion]) -> BoundingBox | None:
    boxes = [line.bbox for line in item.lines if line.page == item.page_start]
    boxes.extend(image.bbox for image in images if image.page == item.page_start)
    if not boxes:
        return None
    merged = boxes[0]
    for box in boxes[1:]:
        merged = merged.union(box)
    return merged


def _first_marks(lines: list[TextLine]) -> int | None:
    for line in lines:
        if _TOTAL_MARKS.search(line.text):
            continue
        match = _MARKS.search(line.text)
        if match:
            return int(match.group(1))
    return None


def _strip_marks(text: str) -> str:
    text = _TOTAL_MARKS.sub("", text)
    text = _MARKS.sub("", text)
    return " ".join(text.split()).strip()


def _join_text(pieces: list[str]) -> str:
    return " ".join(part for part in pieces if part and part.strip()).strip()


def _same_identity(left: TextLine, right: TextLine) -> bool:
    return (
        left.page == right.page
        and left.block_index == right.block_index
        and left.line_index == right.line_index
        and abs(left.y0 - right.y0) < 1.0
        and abs(left.x0 - right.x0) < 1.0
    )


def format_structured_report(paper: StructuredPaper) -> str:
    lines = [
        "STRUCTURED PAPER PARSE REPORT",
        "",
        f"Title: {paper.title or '(none)'}",
        f"Questions detected: {paper.validation.questions_detected}",
        f"Used OCR: {paper.validation.used_ocr}",
        f"Used vision: {paper.validation.used_vision}",
        f"Answers section page: {paper.validation.answers_section_page}",
        "",
    ]
    for question in paper.questions:
        lines.append(f"Q{question.question_number}")
        lines.append(f"Page: {question.source.page_start}-{question.source.page_end}")
        stem = question.stem[:120] + ("..." if len(question.stem) > 120 else "")
        lines.append(f"Stem: {stem or '(empty)'}")
        lines.append(f"Parts: {len(question.parts)}")
        for part in question.parts:
            mark = f" [{part.marks}]" if part.marks is not None else ""
            prompt = part.prompt[:90] + ("..." if len(part.prompt) > 90 else "")
            lines.append(f"  ({part.label}){mark} {prompt}")
            for child in part.children:
                cmark = f" [{child.marks}]" if child.marks is not None else ""
                cprompt = child.prompt[:80] + ("..." if len(child.prompt) > 80 else "")
                lines.append(f"    ({child.label}){cmark} {cprompt}")
        lines.append(f"Tables: {len(question.tables)}")
        lines.append(f"Visual required: {question.visual.required}")
        lines.append(f"Assets: {len(question.visual.assets)}")
        lines.append(f"Status: {question.validation.status.upper()}")
        lines.append("")
        lines.append("--------------------------------")
        lines.append("")
    if paper.validation.issues:
        lines.append("Paper issues:")
        for issue in paper.validation.issues:
            lines.append(f"- {issue.code}: {issue.message}")
    return "\n".join(lines).rstrip() + "\n"
