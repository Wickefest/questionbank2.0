"""MCQ question paper parser: Docling + page image → Gemini → canonical questions."""

from __future__ import annotations

import logging
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Any

from questbank.llm.gemini_client import GeminiClient
from questbank.llm.gemini_question import parse_page_questions
from questbank.pdf.bbox_crop import save_crop
from questbank.pdf.extract_pdf_layout import extract_pdf_layout
from questbank.types.canonical import (
    CompositeVisualOptions,
    GeminiPageQuestion,
    ImageBlock,
    MixedOptions,
    ParsedQuestion,
    SourceRegion,
    TextBlock,
)
from questbank.types.layout import PaperLayout

logger = logging.getLogger(__name__)

_DEFAULT_DPI = 150


def page_docling_context(layout: PaperLayout, page_number: int) -> dict[str, Any]:
    """Serialize Docling/layout evidence for one page for Gemini."""
    page = next((p for p in layout.pages if p.page_number == page_number), None)
    if page is None:
        return {"page": page_number, "lines": [], "tables": [], "images": []}
    lines = [
        {
            "text": line.text,
            "bbox": [line.bbox.y0, line.bbox.x0, line.bbox.y1, line.bbox.x1],
            "reading_order": line.reading_order,
        }
        for line in page.lines
    ]
    tables = [
        {
            "headers": table.headers,
            "rows": table.rows,
            "bbox": [table.bbox.y0, table.bbox.x0, table.bbox.y1, table.bbox.x1],
        }
        for table in page.tables
    ]
    images = [
        {
            "bbox": [img.bbox.y0, img.bbox.x0, img.bbox.y1, img.bbox.x1],
            "block_index": img.block_index,
        }
        for img in page.images
    ]
    return {
        "page": page_number,
        "width": page.width,
        "height": page.height,
        "raw_text": page.raw_text,
        "lines": lines,
        "tables": tables,
        "images": images,
    }


def parse_mcq_questions_gemini(
    pdf_path: str | Path,
    *,
    assets_dir: str | Path,
    client: GeminiClient | None = None,
    layout: PaperLayout | None = None,
    backend: str = "auto",
    ocr: bool | None = None,
    dpi: int = _DEFAULT_DPI,
    max_pages: int | None = None,
    check_gemini: bool = True,
) -> list[ParsedQuestion]:
    """Parse an MCQ question paper into canonical ParsedQuestion records."""
    try:
        import pymupdf
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF and Pillow are required") from exc

    pdf_path = Path(pdf_path)
    out_dir = Path(assets_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = client or GeminiClient()
    if check_gemini:
        llm.ensure_available()

    paper_layout = layout or extract_pdf_layout(pdf_path, backend=backend, ocr=ocr)  # type: ignore[arg-type]
    by_ref: dict[str, ParsedQuestion] = {}

    with pymupdf.open(pdf_path) as doc:
        page_count = doc.page_count if max_pages is None else min(doc.page_count, max_pages)
        for page_index in range(page_count):
            page = doc[page_index]
            page_number = page_index + 1
            pix = page.get_pixmap(dpi=dpi)
            page_image = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
            context = page_docling_context(paper_layout, page_number)

            try:
                result = parse_page_questions(
                    llm,
                    page_image=page_image,
                    page_number=page_number,
                    docling_context=context,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Gemini question parse failed on page %s", page_number)
                # Placeholder review question so validation can flag the page.
                ref = f"page-{page_number}-failed"
                by_ref[ref] = ParsedQuestion(
                    question_ref=ref,
                    content=[TextBlock(value=f"[parse failed on page {page_number}: {exc}]")],
                    options=CompositeVisualOptions(asset="", labels=["A", "B", "C", "D"]),
                    source_page=page_number,
                    source_regions=[SourceRegion(page=page_number)],
                    requires_review=True,
                )
                continue

            for item in result.questions:
                question = _materialize_question(
                    item,
                    page_number=page_number,
                    page_image=page_image,
                    assets_dir=out_dir,
                )
                _merge_into(by_ref, question)

    return sorted(by_ref.values(), key=_ref_sort_key)


def _materialize_question(
    item: GeminiPageQuestion,
    *,
    page_number: int,
    page_image,
    assets_dir: Path,
) -> ParsedQuestion:
    ref = _normalize_ref(item.question_ref)
    content = list(item.content)
    options = deepcopy(item.options)
    slug = _asset_slug(ref)

    # Crop meaningful stem visuals and rewrite image blocks / append new ones.
    stem_index = 0
    for visual in item.stem_visuals:
        stem_index += 1
        asset_name = f"{slug}-stem-{stem_index}.png"
        try:
            save_crop(page_image, visual.bbox, dest=assets_dir / asset_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("stem crop failed for %s: %s", ref, exc)
            return ParsedQuestion(
                question_ref=ref,
                content=content,
                options=options,
                source_page=page_number,
                source_regions=[SourceRegion(page=page_number)],
                requires_review=True,
            )
        # Replace first image block with empty asset, or append.
        replaced = False
        new_content = []
        for block in content:
            if not replaced and getattr(block, "type", None) == "image":
                new_content.append(ImageBlock(asset=asset_name, bbox=list(visual.bbox)))
                replaced = True
            else:
                new_content.append(block)
        if not replaced:
            new_content.append(ImageBlock(asset=asset_name, bbox=list(visual.bbox)))
        content = new_content

    # Composite / mixed visual options: one A-D crop.
    if isinstance(options, CompositeVisualOptions):
        bbox = options.bbox or item.options_bbox
        if not bbox:
            return ParsedQuestion(
                question_ref=ref,
                content=content,
                options=options,
                source_page=page_number,
                source_regions=[SourceRegion(page=page_number)],
                requires_review=True,
            )
        asset_name = f"{slug}-options.png"
        try:
            save_crop(page_image, bbox, dest=assets_dir / asset_name)
            options = CompositeVisualOptions(
                labels=list(options.labels) or ["A", "B", "C", "D"],
                asset=asset_name,
                bbox=list(bbox),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("options crop failed for %s: %s", ref, exc)
            return ParsedQuestion(
                question_ref=ref,
                content=content,
                options=options,
                source_page=page_number,
                source_regions=[SourceRegion(page=page_number)],
                requires_review=True,
            )

    if isinstance(options, MixedOptions) and (options.bbox or item.options_bbox):
        bbox = options.bbox or item.options_bbox
        asset_name = f"{slug}-options.png"
        try:
            assert bbox is not None
            save_crop(page_image, bbox, dest=assets_dir / asset_name)
            options = MixedOptions(
                items=options.items,
                asset=asset_name,
                bbox=list(bbox),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("mixed options crop failed for %s: %s", ref, exc)
            return ParsedQuestion(
                question_ref=ref,
                content=content,
                options=options,
                source_page=page_number,
                source_regions=[SourceRegion(page=page_number)],
                requires_review=True,
            )

    # Strip unresolved image placeholders without assets.
    cleaned = []
    for block in content:
        if getattr(block, "type", None) == "image":
            asset = getattr(block, "asset", "") or ""
            if not asset or not (assets_dir / asset).exists():
                # Keep only if we have a real file; otherwise drop empty placeholders
                if asset and (assets_dir / Path(asset).name).exists():
                    cleaned.append(ImageBlock(asset=Path(asset).name, bbox=getattr(block, "bbox", None)))
                continue
            cleaned.append(ImageBlock(asset=Path(asset).name, bbox=getattr(block, "bbox", None)))
        else:
            cleaned.append(block)

    return ParsedQuestion(
        question_ref=ref,
        content=cleaned,
        options=options,
        source_page=page_number,
        source_regions=[SourceRegion(page=page_number)],
        requires_review=bool(item.requires_review),
    )


def _merge_into(by_ref: dict[str, ParsedQuestion], question: ParsedQuestion) -> None:
    existing = by_ref.get(question.question_ref)
    if existing is None:
        by_ref[question.question_ref] = question
        return
    # Continuation onto another page: append content / regions.
    existing.content = list(existing.content) + list(question.content)
    existing.source_regions = list(existing.source_regions) + list(question.source_regions)
    if question.requires_review:
        existing.requires_review = True
    # Prefer later options only if existing options look empty/incomplete
    by_ref[question.question_ref] = existing


def _normalize_ref(value: str) -> str:
    text = str(value).strip()
    if text.upper().startswith("Q"):
        text = text[1:].lstrip()
    text = text.lstrip("0") or "0"
    if text.isdigit():
        return str(int(text))
    return text


def _asset_slug(ref: str) -> str:
    if ref.isdigit():
        return f"q{int(ref):02d}"
    safe = "".join(ch if ch.isalnum() else "-" for ch in ref.lower())
    return f"q{safe}"


def _ref_sort_key(q: ParsedQuestion) -> tuple:
    ref = q.question_ref
    if ref.isdigit():
        return (0, int(ref))
    return (1, ref)


__all__ = ["page_docling_context", "parse_mcq_questions_gemini"]
