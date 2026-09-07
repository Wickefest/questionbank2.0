"""Gemini answer / mark-scheme parsing (source reconstruction only)."""

from __future__ import annotations

import json
from typing import Any

from questbank.llm.gemini_client import GeminiClient
from questbank.types.canonical import GeminiAnswerPageResult

ANSWER_PARSE_INSTRUCTION = """\
You are extracting official MCQ answers from a Chemistry mark scheme / answer key page.

You receive an image of the original answer document page and optional Docling text.

Extract only what the mark scheme states:
- question reference
- correct option letter (A/B/C/D)
- official explanation text IF present on the page

Rules:
- Do NOT invent explanations.
- If the page only lists letters (e.g. "1 B  2 A"), set explanation to null.
- Do NOT solve chemistry questions yourself.
- Do NOT add educational commentary.
- Ignore headers, footers, school branding, topic revision checklists, and
  structured Paper 2 mark schemes that are not MCQ keys.
- Preserve official wording of any explanation that is actually printed.

Return only data conforming to the supplied structured-output schema.
"""


def parse_answer_page(
    client: GeminiClient,
    *,
    page_image=None,
    page_number: int,
    docling_context: list[dict[str, Any]] | dict[str, Any] | str | None = None,
    page_text: str | None = None,
) -> GeminiAnswerPageResult:
    chunks: list[str] = [ANSWER_PARSE_INSTRUCTION, f"Page number: {page_number}"]
    if page_text:
        chunks.append(f"Extracted page text:\n{page_text}")
    if docling_context is not None:
        if isinstance(docling_context, str):
            ctx = docling_context
        else:
            ctx = json.dumps(docling_context, ensure_ascii=False, indent=2)
        chunks.append(f"Docling candidate extraction:\n{ctx}")

    prompt = "\n\n".join(chunks)
    return client.generate_structured(
        prompt=prompt,
        response_model=GeminiAnswerPageResult,
        image=page_image,
    )


__all__ = ["ANSWER_PARSE_INSTRUCTION", "parse_answer_page"]
