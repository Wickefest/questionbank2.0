from __future__ import annotations

import json
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any

from questbank.types.layout import BoundingBox
from questbank.types.question import (
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

_DEFAULT_DPI = 180
_DEFAULT_MODEL = "gemini-2.0-flash"
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S | re.I)


def parse_structured_paper_vision(
    pdf_path: str | Path,
    *,
    api_key: str | None = None,
    model_name: str | None = None,
    dpi: int = _DEFAULT_DPI,
    extract_visuals: bool = True,
    visuals_dir: str | Path | None = None,
    stop_at_answers: bool = True,
) -> StructuredPaper:
    """Parse a scanned structured paper with a vision LLM (Gemini).

    Retains questbank ``StructuredPaper`` schema. Does not upload to Supabase —
    that stays in the API layer. Requires ``GEMINI_API_KEY`` (or ``api_key``).
    """
    try:
        import google.generativeai as genai
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "google-generativeai is required for --engine vision. "
            "Install with: pip install google-generativeai pillow"
        ) from exc

    try:
        import pymupdf
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF and Pillow are required for vision parsing") from exc

    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY (or pass api_key=...) for vision parsing")

    pdf_path = Path(pdf_path)
    out_dir = Path(visuals_dir) if visuals_dir else Path("output") / "ammonia-visuals"
    if extract_visuals:
        out_dir.mkdir(parents=True, exist_ok=True)
        for stale in out_dir.glob("q*.png"):
            stale.unlink(missing_ok=True)

    genai.configure(api_key=key)
    model = genai.GenerativeModel(model_name or os.environ.get("GEMINI_MODEL", _DEFAULT_MODEL))

    title: str | None = None
    answers_page: int | None = None
    by_number: dict[int, StructuredQuestion] = {}
    issues: list[ValidationIssue] = []

    with pymupdf.open(pdf_path) as doc:
        for page_index in range(doc.page_count):
            page = doc[page_index]
            page_number = page_index + 1
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            png_bytes = pix.tobytes("png")
            page_image = Image.open(BytesIO(png_bytes)).convert("RGB")

            try:
                payload = _ask_page(model, page_image, page_number)
            except Exception as exc:  # noqa: BLE001
                issues.append(
                    ValidationIssue(
                        code="VISION_PAGE_FAILED",
                        message=f"Page {page_number}: {exc}",
                        severity="warning",
                    )
                )
                continue

            if payload.get("is_answers_section"):
                answers_page = answers_page or page_number
                if stop_at_answers:
                    break

            if not title and payload.get("page_title"):
                title = str(payload["page_title"]).strip() or None

            width, height = page_image.size
            for item in payload.get("questions") or []:
                try:
                    question = _item_to_question(
                        item,
                        page_number=page_number,
                        page_image=page_image if extract_visuals else None,
                        page_width=width,
                        page_height=height,
                        visuals_dir=out_dir if extract_visuals else None,
                    )
                except Exception as exc:  # noqa: BLE001
                    issues.append(
                        ValidationIssue(
                            code="VISION_ITEM_FAILED",
                            message=f"Page {page_number} item: {exc}",
                            severity="warning",
                        )
                    )
                    continue

                existing = by_number.get(question.question_number)
                if existing is None:
                    by_number[question.question_number] = question
                else:
                    by_number[question.question_number] = _merge_questions(existing, question)

    questions = [by_number[n] for n in sorted(by_number)]
    if not questions:
        issues.append(
            ValidationIssue(
                code="NO_QUESTIONS",
                message="Vision parser detected no questions",
                severity="error",
            )
        )

    return StructuredPaper(
        title=title,
        questions=questions,
        validation=StructuredPaperValidation(
            questions_expected=None,
            questions_detected=len(questions),
            answers_section_page=answers_page,
            used_ocr=False,
            used_vision=True,
            issues=issues,
        ),
    )


def _ask_page(model, page_image, page_number: int) -> dict[str, Any]:
    prompt = f"""You are parsing an O-Level Pure Chemistry structured (written) exam page.
This is page {page_number}.

Return ONLY valid JSON (no markdown) with this shape:
{{
  "page_title": "string or null",
  "is_answers_section": false,
  "questions": [
    {{
      "question_number": 1,
      "box_2d": [ymin, xmin, ymax, xmax],
      "stem": "shared intro text before parts, LaTeX ok for formulas",
      "marks_total": 4,
      "parts": [
        {{
          "label": "a",
          "prompt": "part prompt text",
          "marks": 1,
          "children": [
            {{"label": "i", "prompt": "...", "marks": 1, "children": []}}
          ]
        }}
      ],
      "has_diagram": true
    }}
  ]
}}

Rules:
- box_2d uses integer coords in 0-1000 normalized space: [ymin, xmin, ymax, xmax], covering the full question including diagrams/tables/options for that number.
- If this page is a mark scheme / Answers section, set is_answers_section=true and questions=[].
- Prefer nested (i)/(ii) under lettered (a)/(b) parts.
- Transcribe chemistry carefully (subscripts, equilibrium arrows, delta H).
- Ignore answer dotted lines.
- Only include questions that START on this page (continuation pages may add parts to an existing number).
"""
    response = model.generate_content([prompt, page_image])
    text = getattr(response, "text", None) or ""
    return _parse_json_object(text)


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = _JSON_FENCE.search(cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    data = json.loads(cleaned)
    if isinstance(data, list):
        return {"page_title": None, "is_answers_section": False, "questions": data}
    if not isinstance(data, dict):
        raise ValueError("Vision response is not a JSON object")
    return data


def _item_to_question(
    item: dict[str, Any],
    *,
    page_number: int,
    page_image,
    page_width: int,
    page_height: int,
    visuals_dir: Path | None,
) -> StructuredQuestion:
    number = int(item["question_number"])
    stem = str(item.get("stem") or "").strip()
    parts = [_parse_part(part) for part in (item.get("parts") or [])]
    marks_total = item.get("marks_total")
    marks_total = int(marks_total) if marks_total is not None else None

    assets: list[VisualAsset] = []
    bbox = _box2d_to_bbox(item.get("box_2d"), page_width, page_height)
    if page_image is not None and visuals_dir is not None and bbox is not None:
        asset = _crop_and_save(
            page_image,
            bbox,
            page_number=page_number,
            question_number=number,
            visuals_dir=visuals_dir,
        )
        if asset:
            assets.append(asset)

    has_diagram = bool(item.get("has_diagram")) or bool(assets)
    return StructuredQuestion(
        question_number=number,
        source=SourceRegion(
            page_start=page_number,
            page_end=page_number,
            bounding_box=bbox,
        ),
        stem=stem,
        parts=parts,
        marks_total=marks_total,
        tables=[],
        visual=VisualExpectation(
            required=has_diagram or bool(assets),
            extraction_pending=False,
            assets=assets,
        ),
        validation=_validate_question(stem, parts),
    )


def _parse_part(raw: dict[str, Any]) -> StructuredPart:
    children = [_parse_part(child) for child in (raw.get("children") or [])]
    marks = raw.get("marks")
    return StructuredPart(
        label=str(raw.get("label") or "").strip().lower(),
        prompt=str(raw.get("prompt") or "").strip(),
        marks=int(marks) if marks is not None else None,
        children=children,
    )


def box2d_to_pixel_box(
    box_2d: list[int] | tuple[int, ...] | None,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    """Convert Gemini-style [ymin,xmin,ymax,xmax] in 0-1000 space to pixel crop box."""
    if not box_2d or len(box_2d) != 4:
        return None
    ymin, xmin, ymax, xmax = [int(value) for value in box_2d]
    left = max(0, min(width, int((xmin / 1000) * width)))
    top = max(0, min(height, int((ymin / 1000) * height)))
    right = max(0, min(width, int((xmax / 1000) * width)))
    bottom = max(0, min(height, int((ymax / 1000) * height)))
    if right - left < 4 or bottom - top < 4:
        return None
    return left, top, right, bottom


def _box2d_to_bbox(box_2d, width: int, height: int) -> BoundingBox | None:
    # Store PDF-ish coords assuming page render maps 1:1 with pixmap pixels at given DPI.
    # For source metadata we keep pixel space normalized back to PDF points via /dpi*72 later if needed.
    # Here we store pixel crop box scaled as if page width/height were the pixmap size.
    pixels = box2d_to_pixel_box(box_2d, width, height)
    if pixels is None:
        return None
    left, top, right, bottom = pixels
    # Convert pixmap pixels to approximate PDF points (dpi assumed by caller via render).
    # Use page point space relative to pixmap: x_pdf = x_px * 72 / dpi is unknown here,
    # so keep coordinates in the rendered pixel space for crop paths; source bbox is still useful.
    return BoundingBox(x0=float(left), y0=float(top), x1=float(right), y1=float(bottom))


def _crop_and_save(
    page_image,
    bbox: BoundingBox,
    *,
    page_number: int,
    question_number: int,
    visuals_dir: Path,
) -> VisualAsset | None:
    crop = page_image.crop((int(bbox.x0), int(bbox.y0), int(bbox.x1), int(bbox.y1)))
    path = visuals_dir / f"q{question_number:02d}-p{page_number:02d}-vision.png"
    crop.save(path, format="PNG")
    return VisualAsset(
        role="stem",
        option_label=None,
        page=page_number,
        bounding_box=bbox,
        path=str(path).replace("\\", "/"),
        mime_type="image/png",
    )


def _merge_questions(left: StructuredQuestion, right: StructuredQuestion) -> StructuredQuestion:
    """Merge continuation-page content into an earlier question."""
    parts = list(left.parts)
    existing_labels = {part.label for part in parts}
    for part in right.parts:
        if part.label in existing_labels:
            # Append unique child prompts under matching parent when possible.
            parent = next(p for p in parts if p.label == part.label)
            child_labels = {child.label for child in parent.children}
            extra_children = [c for c in part.children if c.label not in child_labels]
            if extra_children or (part.prompt and part.prompt not in parent.prompt):
                merged_prompt = parent.prompt
                if part.prompt and part.prompt not in parent.prompt:
                    merged_prompt = f"{parent.prompt} {part.prompt}".strip()
                idx = parts.index(parent)
                parts[idx] = parent.model_copy(
                    update={
                        "prompt": merged_prompt,
                        "children": [*parent.children, *extra_children],
                    }
                )
        else:
            parts.append(part)

    assets = list(left.visual.assets) + list(right.visual.assets)
    stem = left.stem if left.stem.strip() else right.stem
    return left.model_copy(
        update={
            "stem": stem,
            "parts": parts,
            "marks_total": left.marks_total or right.marks_total,
            "source": SourceRegion(
                page_start=left.source.page_start,
                page_end=max(left.source.page_end, right.source.page_end),
                bounding_box=left.source.bounding_box or right.source.bounding_box,
            ),
            "visual": VisualExpectation(
                required=left.visual.required or right.visual.required or bool(assets),
                extraction_pending=False,
                assets=assets,
            ),
            "validation": _validate_question(stem, parts),
        }
    )


def _validate_question(stem: str, parts: list[StructuredPart]) -> QuestionValidation:
    issues: list[ValidationIssue] = []
    if not stem.strip() and not parts:
        issues.append(
            ValidationIssue(
                code="EMPTY_QUESTION",
                message="Question has no stem or parts",
                severity="error",
            )
        )
    status = "review" if issues else "pass"
    return QuestionValidation(status=status, issues=issues)
