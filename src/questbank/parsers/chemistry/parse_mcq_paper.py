from __future__ import annotations

import re
from pathlib import Path

from questbank.normalize.chemistry import annotate_chemistry
from questbank.parsers.chemistry.detect_question_boundaries import (
    QuestionSlice,
    detect_question_boundaries,
)
from questbank.parsers.chemistry.parse_mcq_options import (
    find_option_run,
    is_image_annotation,
    parse_mcq_options,
)
from questbank.parsers.chemistry.parse_tables import (
    line_is_figure_text,
    line_is_table_text,
    merge_options_with_tables,
    tables_for_slice,
)
from questbank.parsers.chemistry.visual_cues import stem_requires_visual
from questbank.pdf.extract_pdf_layout import LayoutBackend, extract_pdf_layout
from questbank.pdf.extract_visuals import (
    assign_images_to_questions,
    build_slice_bands,
    extract_question_visuals,
    promote_visual_options,
)
from questbank.types.layout import BoundingBox, ImageRegion, PaperLayout, TextLine
from questbank.types.question import (
    ParsedOption,
    ParsedPaper,
    ParsedQuestion,
    ParsedTable,
    SourceRegion,
    VisualExpectation,
)
from questbank.validation.validate_parsed_paper import validate_parsed_paper


def parse_chemistry_paper_1(
    pdf_path: str | Path,
    expected_count: int = 40,
    layout: PaperLayout | None = None,
    backend: LayoutBackend = "auto",
    extract_visuals: bool = False,
    visuals_dir: str | Path | None = None,
    ocr: bool | None = None,
) -> ParsedPaper:
    pdf_path = Path(pdf_path)
    paper_layout = layout or extract_pdf_layout(pdf_path, backend=backend, ocr=ocr)
    slices = detect_question_boundaries(paper_layout, expected_count=expected_count)

    starts = [(item.number, item.page_start, item.start.line.y0) for item in slices]
    final_page = paper_layout.page_count or (slices[-1].page_end if slices else 1)
    bands = build_slice_bands(starts, final_page=final_page)
    all_images = [image for page in paper_layout.pages for image in page.images]
    images_by_question = assign_images_to_questions(
        slices_meta=bands,
        layout_images=all_images,
    )

    questions: list[ParsedQuestion] = []
    for item in slices:
        question, images = _parse_slice(
            item,
            paper_layout,
            images=images_by_question.get(item.number, []),
        )
        questions.append(question)
        images_by_question[question.question_number] = images

    if extract_visuals:
        out_dir = Path(visuals_dir) if visuals_dir else Path("output") / "visuals"
        questions = extract_question_visuals(
            pdf_path, questions, images_by_question, out_dir
        )

    return validate_parsed_paper(questions, expected_count=expected_count)


def _parse_slice(
    item: QuestionSlice,
    layout: PaperLayout,
    images: list[ImageRegion] | None = None,
) -> tuple[ParsedQuestion, list[ImageRegion]]:
    images = list(images) if images is not None else _images_for_slice(item, layout)
    options = parse_mcq_options(item.lines, images, item.start.line)
    tables = tables_for_slice(item, layout, images)
    options = merge_options_with_tables(options, tables)
    stem = _parse_stem(item, options, images, tables)
    provisional = ParsedQuestion(
        question_number=item.number,
        source=SourceRegion(
            page_start=item.page_start,
            page_end=item.page_end,
            bounding_box=_question_bbox(item, images),
        ),
        stem=stem,
        options=options,
        tables=tables,
        chemistry=annotate_chemistry(
            stem,
            {label: option.text for label, option in options.items()},
        ),
        visual=VisualExpectation(required=False, extraction_pending=False),
        validation={"status": "pass", "issues": []},
    )
    provisional, images = promote_visual_options(provisional, images)
    options = provisional.options
    stem = provisional.stem
    visual_required = stem_requires_visual(stem) or any(
        option.requires_visual for option in options.values()
    )
    chemistry = annotate_chemistry(
        stem,
        {label: option.text for label, option in options.items()},
    )
    question = ParsedQuestion(
        question_number=item.number,
        source=SourceRegion(
            page_start=item.page_start,
            page_end=item.page_end,
            bounding_box=_question_bbox(item, images),
        ),
        stem=stem,
        options=options,
        tables=tables,
        chemistry=chemistry,
        visual=VisualExpectation(
            required=visual_required,
            extraction_pending=visual_required,
        ),
        validation={"status": "pass", "issues": []},
    )
    return question, images


def _parse_stem(
    item: QuestionSlice,
    options: dict[str, ParsedOption],
    images: list[ImageRegion],
    tables: list[ParsedTable],
) -> str:
    del options
    run = find_option_run(item.lines, item.start.line)
    first_option = run[0].line if run else None
    pieces: list[str] = []
    if item.start.stem_prefix:
        pieces.append(item.start.stem_prefix)
    for line in item.lines:
        if _same_identity(line, item.start.line):
            continue
        if first_option and _same_identity(line, first_option):
            break
        if first_option and (line.page, line.y0, line.x0) >= (
            first_option.page,
            first_option.y0,
            first_option.x0,
        ):
            break
        # Lone A-D labels belong to option figures, not the stem.
        if line.text.strip() in {"A", "B", "C", "D"}:
            continue
        if is_image_annotation(line, images):
            continue
        if line_is_figure_text(line, images):
            continue
        if line_is_table_text(line, tables):
            continue
        pieces.append(line.text.strip())
    return _join_stem(pieces)


def _join_stem(pieces: list[str]) -> str:
    text = " ".join(part for part in pieces if part)
    text = " ".join(text.split())
    return re.sub(r"(?i)\s*-\s*end of section\s*-?\s*$", "", text).strip()


def _images_for_slice(item: QuestionSlice, layout: PaperLayout) -> list[ImageRegion]:
    y_start = item.start.line.y0
    next_page_limit = item.page_end
    images: list[ImageRegion] = []
    last_line = item.lines[-1]
    for page in layout.pages:
        if page.page_number < item.page_start or page.page_number > next_page_limit:
            continue
        for image in page.images:
            if page.page_number == item.page_start and image.bbox.y1 < y_start - 8:
                continue
            if page.page_number == item.page_end and image.bbox.y0 > last_line.y1 + 40:
                continue
            images.append(image)
    return images


def _question_bbox(item: QuestionSlice, images: list[ImageRegion]) -> BoundingBox | None:
    boxes = [line.bbox for line in item.lines if line.page == item.page_start]
    boxes.extend(image.bbox for image in images if image.page == item.page_start)
    if not boxes:
        return None
    merged = boxes[0]
    for box in boxes[1:]:
        merged = merged.union(box)
    return merged


def _line_identity(line: TextLine) -> tuple[int, int, int, float, float]:
    return (line.page, line.block_index, line.line_index, line.x0, line.y0)


def _same_identity(left: TextLine, right: TextLine) -> bool:
    return _line_identity(left) == _line_identity(right)
