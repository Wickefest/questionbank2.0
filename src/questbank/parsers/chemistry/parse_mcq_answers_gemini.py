"""Answer / mark-scheme PDF parser via Docling + Gemini."""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

from questbank.llm.gemini_answer import parse_answer_page
from questbank.llm.gemini_client import GeminiClient
from questbank.parsers.chemistry.parse_mcq_gemini import page_docling_context
from questbank.pdf.extract_pdf_layout import extract_pdf_layout
from questbank.types.canonical import ParsedAnswer
from questbank.types.ingest import normalize_question_ref

logger = logging.getLogger(__name__)

_DEFAULT_DPI = 150


def parse_mcq_answers_gemini(
    pdf_path: str | Path,
    *,
    client: GeminiClient | None = None,
    backend: str = "auto",
    ocr: bool | None = None,
    dpi: int = _DEFAULT_DPI,
    max_pages: int | None = None,
    check_gemini: bool = True,
) -> list[ParsedAnswer]:
    """Parse an answer/mark-scheme PDF into canonical ParsedAnswer records."""
    try:
        import pymupdf
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF and Pillow are required") from exc

    pdf_path = Path(pdf_path)
    llm = client or GeminiClient()
    if check_gemini:
        llm.ensure_available()

    layout = extract_pdf_layout(pdf_path, backend=backend, ocr=ocr)  # type: ignore[arg-type]
    by_ref: dict[str, ParsedAnswer] = {}

    with pymupdf.open(pdf_path) as doc:
        page_count = doc.page_count if max_pages is None else min(doc.page_count, max_pages)
        for page_index in range(page_count):
            page = doc[page_index]
            page_number = page_index + 1
            page_text = page.get_text("text") or ""
            pix = page.get_pixmap(dpi=dpi)
            page_image = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
            context = page_docling_context(layout, page_number)

            try:
                result = parse_answer_page(
                    llm,
                    page_image=page_image,
                    page_number=page_number,
                    docling_context=context,
                    page_text=page_text,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Gemini answer parse failed on page %s", page_number)
                continue

            for entry in result.answers:
                ref = _canonical_ref(entry.question_ref)
                existing = by_ref.get(ref)
                if existing is None:
                    by_ref[ref] = ParsedAnswer(
                        question_ref=ref,
                        answer=entry.answer,
                        explanation=entry.explanation,
                    )
                    continue
                # Prefer entry that carries an official explanation.
                if existing.explanation is None and entry.explanation:
                    by_ref[ref] = ParsedAnswer(
                        question_ref=ref,
                        answer=entry.answer,
                        explanation=entry.explanation,
                    )

    return sorted(by_ref.values(), key=_answer_sort_key)


def _canonical_ref(value: str) -> str:
    # normalize_question_ref returns "Q4"; strip Q for canonical "4"
    normalized = normalize_question_ref(value)
    if normalized.startswith("Q"):
        return normalized[1:]
    return normalized


def _answer_sort_key(a: ParsedAnswer) -> tuple:
    if a.question_ref.isdigit():
        return (0, int(a.question_ref))
    return (1, a.question_ref)


__all__ = ["parse_mcq_answers_gemini"]
