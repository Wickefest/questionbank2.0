"""Gemini question reconciliation: page image + Docling evidence → canonical questions."""

from __future__ import annotations

import json
from typing import Any

from questbank.llm.gemini_client import GeminiClient
from questbank.types.canonical import GeminiPageParseResult

QUESTION_RECONCILE_INSTRUCTION = """\
You are reconstructing Chemistry examination questions from their original source.

You receive an image of the original examination page together with a candidate
extraction produced by Docling.

The page image is the authoritative source.
Docling is supporting evidence and may contain extraction errors.

Produce the faithful final representation of every examination question visible
in the supplied source.

Preserve:
- wording
- order
- option labels
- table row/column relationships
- mathematical notation
- chemical notation
- units
- diagrams
- graphs
- chemical structures
- captions
- labels needed to answer the question

Do not:
- solve the question
- add explanations
- paraphrase the source
- add educational context
- fix the examiner's wording
- invent unreadable content
- include headers, page numbers, school branding, instructions or
  neighbouring questions as question content

Use the original page when Docling and the image disagree.

Represent answer options as one of:
text, math, table, composite_visual, mixed.

For composite visual answer options, identify one bounding box containing
the complete A-D option area (labels + all choices + captions/frames).

For a meaningful diagram/graph inside the stem, return a bounding box for
that visual in stem_visuals. Do NOT invent stem visuals for ordinary text questions.

For tables, preserve every row and every column. Never flatten H2 | O2 into H2O2.

Bounding boxes use normalized coordinates [ymin, xmin, ymax, xmax] on a 0-1000 scale.

Set requires_review=true only when the source cannot be reconstructed safely.
Return only data conforming to the supplied structured-output schema.
"""


def serialize_docling_page_context(blocks: list[dict[str, Any]] | dict[str, Any] | str) -> str:
    if isinstance(blocks, str):
        return blocks
    return json.dumps(blocks, ensure_ascii=False, indent=2)


def parse_page_questions(
    client: GeminiClient,
    *,
    page_image,
    page_number: int,
    docling_context: list[dict[str, Any]] | dict[str, Any] | str,
) -> GeminiPageParseResult:
    """Reconcile one page into structured questions."""
    context_json = serialize_docling_page_context(docling_context)
    prompt = (
        f"{QUESTION_RECONCILE_INSTRUCTION}\n\n"
        f"Page number: {page_number}\n\n"
        f"Docling candidate extraction (may be wrong):\n{context_json}\n"
    )
    return client.generate_structured(
        prompt=prompt,
        response_model=GeminiPageParseResult,
        image=page_image,
    )


__all__ = [
    "QUESTION_RECONCILE_INSTRUCTION",
    "parse_page_questions",
    "serialize_docling_page_context",
]
