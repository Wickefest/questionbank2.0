from __future__ import annotations

from pathlib import Path

from questbank.types.layout import BoundingBox, ImageRegion
from questbank.types.question import (
    OPTION_LABELS,
    OptionLabel,
    ParsedOption,
    ParsedQuestion,
    VisualAsset,
    VisualExpectation,
)

_OPTION_GRID_Y_GAP = 30.0
_STALE_VISUAL = "q*-*.png"


def extract_question_visuals(
    pdf_path: str | Path,
    questions: list[ParsedQuestion],
    images_by_question: dict[int, list[ImageRegion]],
    output_dir: str | Path,
) -> list[ParsedQuestion]:
    """Crop stem/option visuals from the PDF and attach file paths for API consumers."""
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF is required for visual extraction") from exc

    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _clear_stale_visuals(output_dir)

    bands = _question_bands(questions)
    updated: list[ParsedQuestion] = []
    with pymupdf.open(pdf_path) as doc:
        for question in questions:
            images = list(images_by_question.get(question.question_number, []))
            question, images = promote_visual_options(question, images)
            if _needs_band_fallback(question, images):
                fallback = _band_fallback_image(question, bands, doc)
                if fallback is not None:
                    images = [fallback]
                    question, images = promote_visual_options(question, images)
            assets = _crop_assets(doc, question, images, output_dir)
            visual = _visual_with_assets(question.visual, assets)
            updated.append(question.model_copy(update={"visual": visual}))
    return updated


def _clear_stale_visuals(output_dir: Path) -> None:
    """Remove prior run crops so leftover qNN-stem-2.png cannot mislead review."""
    for path in output_dir.glob(_STALE_VISUAL):
        try:
            path.unlink()
        except OSError:
            continue


def _option_looks_empty_or_label_echo(option: ParsedOption) -> bool:
    text = (option.text or "").strip()
    if not text:
        return True
    if text in {"...", "…", "[diagram]", "[structure]", "<visual>", "visual"}:
        return True
    if text.upper() == option.label:
        return True
    if len(text) == 1 and text.upper() in OPTION_LABELS:
        return True
    return False


def _needs_band_fallback(question: ParsedQuestion, images: list[ImageRegion]) -> bool:
    """Only invent a crop when Docling missed a stem diagram — never for text MCQs.

    Graphics A–D options require real layout pictures. Band-cropping a text
    question produces fake options.png files (whole stem / page footer).
    """
    if images:
        return False
    # Do not fabricate options.png from the question text band.
    if any(option.requires_visual for option in question.options.values()):
        return False
    return bool(question.visual.required)


def _question_bands(
    questions: list[ParsedQuestion],
) -> dict[int, tuple[int, float, int, float]]:
    ordered = sorted(
        questions,
        key=lambda q: (
            q.source.page_start,
            q.source.bounding_box.y0 if q.source.bounding_box else 0.0,
        ),
    )
    bands: dict[int, tuple[int, float, int, float]] = {}
    for index, question in enumerate(ordered):
        y0 = question.source.bounding_box.y0 if question.source.bounding_box else 0.0
        if index + 1 < len(ordered):
            nxt = ordered[index + 1]
            next_page = nxt.source.page_start
            next_y0 = nxt.source.bounding_box.y0 if nxt.source.bounding_box else 10_000.0
        else:
            next_page = question.source.page_end + 1
            next_y0 = 10_000.0
        bands[question.question_number] = (
            question.source.page_start,
            y0,
            next_page,
            next_y0,
        )
    return bands


def _band_fallback_image(
    question: ParsedQuestion,
    bands: dict[int, tuple[int, float, int, float]],
    doc,
) -> ImageRegion | None:
    """When Docling misses drawings, crop the question band as a single figure."""
    band = bands.get(question.question_number)
    bbox = question.source.bounding_box
    if band is None or bbox is None:
        return None
    page_start, y0, page_end, y_end = band
    page_index = page_start - 1
    if page_index < 0 or page_index >= doc.page_count:
        return None
    page = doc[page_index]
    page_height = float(page.rect.height)
    page_width = float(page.rect.width)
    # Prefer content below the stem text when options are visual-only.
    visual_options = all(
        question.options[label].requires_visual for label in OPTION_LABELS
    )
    if visual_options:
        stem_bottom = bbox.y1
        lower = stem_bottom + 4.0
        upper = y_end - 2.0 if page_end == page_start else page_height - 36.0
        if upper - lower < 40:
            lower = y0
            upper = y_end if page_end == page_start else page_height - 36.0
    else:
        lower = y0
        upper = y_end if page_end == page_start else page_height - 36.0
    upper = min(upper, page_height - 8.0)
    lower = max(0.0, lower)
    if upper - lower < 24:
        return None
    return ImageRegion(
        page=page_start,
        bbox=BoundingBox(x0=36.0, y0=lower, x1=page_width - 36.0, y1=upper),
        block_index=-1,
    )

def assign_images_to_questions(
    slices_meta: list[tuple[int, int, float, int, float]],
    layout_images: list[ImageRegion],
) -> dict[int, list[ImageRegion]]:
    """Assign each image to at most one question using [start, next_start) bands.

    slices_meta entries: (number, page_start, y_start, page_end_exclusive, y_end_exclusive)
    """
    assigned: dict[int, list[ImageRegion]] = {number: [] for number, *_ in slices_meta}
    claimed: set[tuple[float, ...]] = set()

    for image in layout_images:
        key = (
            float(image.page),
            round(image.bbox.x0, 2),
            round(image.bbox.y0, 2),
            round(image.bbox.x1, 2),
            round(image.bbox.y1, 2),
        )
        if key in claimed:
            continue
        cy = (image.bbox.y0 + image.bbox.y1) / 2
        owner: int | None = None
        for number, page_start, y_start, page_end, y_end in slices_meta:
            if not _image_in_band(image.page, cy, page_start, y_start, page_end, y_end):
                continue
            owner = number
            break
        if owner is None:
            continue
        assigned[owner].append(image)
        claimed.add(key)
    return assigned


def build_slice_bands(
    starts: list[tuple[int, int, float]],
    final_page: int,
) -> list[tuple[int, int, float, int, float]]:
    """Build exclusive end bands from (number, page, y0) starts."""
    bands: list[tuple[int, int, float, int, float]] = []
    for index, (number, page, y0) in enumerate(starts):
        if index + 1 < len(starts):
            next_page, next_y = starts[index + 1][1], starts[index + 1][2]
            bands.append((number, page, y0, next_page, next_y))
        else:
            bands.append((number, page, y0, final_page, 10_000.0))
    return bands


def _image_in_band(
    page: int,
    cy: float,
    page_start: int,
    y_start: float,
    page_end: int,
    y_end: float,
) -> bool:
    if page < page_start or page > page_end:
        return False
    if page_start == page_end:
        return y_start - 4 <= cy < y_end - 1
    if page == page_start:
        return cy >= y_start - 4
    if page == page_end:
        return cy < y_end - 1
    return True


def promote_visual_options(
    question: ParsedQuestion,
    images: list[ImageRegion],
) -> tuple[ParsedQuestion, list[ImageRegion]]:
    """If A–D have no extractable text and pictures exist, use ONE options crop.

    Stem graphs / organic structures stay separate stem crops. Graphics options
    are always merged into a single options.png (never per-letter crops).
    Text-only questions with no Docling pictures are left alone.
    """
    from questbank.parsers.chemistry.visual_cues import stem_requires_visual

    if not images:
        return question, images

    no_text = [
        label
        for label in OPTION_LABELS
        if _option_looks_empty_or_label_echo(question.options[label])
    ]
    already_graphics = sum(
        1 for label in OPTION_LABELS if question.options[label].requires_visual
    )
    # Empty A–D + layout pictures (or already flagged graphics) → options grid.
    treat_as_graphics_options = len(no_text) >= 3 or already_graphics >= 3
    if not treat_as_graphics_options:
        return question, images

    stem_images, option_images = _split_stem_and_option_images(images)
    if not option_images:
        if len(images) == 1:
            # Single figure + empty A-D: options grid, unless stem itself needs the figure.
            if stem_requires_visual(question.stem) and not any(
                question.options[label].requires_visual for label in OPTION_LABELS
            ):
                return question, images
            stem_images, option_images = [], list(images)
        elif len(images) >= 2:
            ordered = sorted(images, key=lambda img: (img.page, img.bbox.y0, img.bbox.x0))
            stem_images, option_images = ordered[:-1], ordered[-1:]
        else:
            return question, images

    options = {
        label: ParsedOption(label=label, text=None, requires_visual=True)
        for label in OPTION_LABELS
    }
    visual = VisualExpectation(
        required=True,
        extraction_pending=True,
        assets=list(question.visual.assets),
    )
    merged_options = _merge_image_regions(option_images)
    remapped = list(stem_images)
    if merged_options is not None:
        remapped.append(merged_options)
    return question.model_copy(update={"options": options, "visual": visual}), remapped


def _split_stem_and_option_images(
    images: list[ImageRegion],
) -> tuple[list[ImageRegion], list[ImageRegion]]:
    """Split stem diagrams (above) from the A–D options figure block (below)."""
    if len(images) <= 1:
        return list(images), []
    ordered = sorted(images, key=lambda img: (img.page, img.bbox.y0, img.bbox.x0))
    gaps: list[tuple[float, int]] = []
    for index in range(len(ordered) - 1):
        gap = ordered[index + 1].bbox.y0 - ordered[index].bbox.y1
        gaps.append((gap, index))
    gaps.sort(reverse=True)
    best_gap, split_at = gaps[0]
    below = ordered[split_at + 1 :]
    # Stem figure(s) above a multi-cell option block.
    if len(below) >= 2 and best_gap >= 8:
        return ordered[: split_at + 1], below
    # Row of 3+ small option tiles → treat as one options grid.
    if best_gap < _OPTION_GRID_Y_GAP and len(ordered) >= 3:
        return ordered[:1], ordered[1:]
    if best_gap < 8:
        return [], ordered
    # Default: everything above the last gap is stem; last group is options.
    return ordered[: split_at + 1], ordered[split_at + 1 :]


def _merge_image_regions(images: list[ImageRegion]) -> ImageRegion | None:
    if not images:
        return None
    if len(images) == 1:
        return images[0]
    pages = {image.page for image in images}
    if len(pages) != 1:
        # Keep first page group only for a single combined crop.
        page = min(pages)
        images = [image for image in images if image.page == page]
    merged = images[0].bbox
    for image in images[1:]:
        merged = merged.union(image.bbox)
    return ImageRegion(page=images[0].page, bbox=merged, block_index=images[0].block_index)


def _crop_assets(
    doc,
    question: ParsedQuestion,
    images: list[ImageRegion],
    output_dir: Path,
) -> list[VisualAsset]:
    if not images:
        return []

    assets: list[VisualAsset] = []
    visual_options = any(option.requires_visual for option in question.options.values())

    if visual_options:
        stem_images, option_images = _split_stem_and_option_images(images)
        if not option_images and images:
            # Promote already merged options into a trailing region.
            stem_images, option_images = images[:-1], images[-1:]
        if option_images:
            merged = _merge_image_regions(option_images)
            if merged is not None:
                asset = _render_image(
                    doc,
                    merged,
                    output_dir / f"q{question.question_number:02d}-options.png",
                    role="option",
                    option_label=None,
                )
                if asset:
                    assets.append(asset)
        stem_images = _unique_images(stem_images)
    else:
        stem_images = _unique_images(images)

    for index, image in enumerate(stem_images):
        suffix = "" if len(stem_images) == 1 else f"-{index + 1}"
        asset = _render_image(
            doc,
            image,
            output_dir / f"q{question.question_number:02d}-stem{suffix}.png",
            role="stem",
            option_label=None,
        )
        if asset:
            assets.append(asset)
    return assets


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


def _render_image(
    doc,
    image: ImageRegion,
    path: Path,
    role: str,
    option_label: OptionLabel | None,
) -> VisualAsset | None:
    page_index = image.page - 1
    if page_index < 0 or page_index >= doc.page_count:
        return None
    page = doc[page_index]
    rect = _clip_rect(page, image.bbox)
    if rect is None:
        return None
    try:
        import pymupdf

        pix = page.get_pixmap(clip=rect, matrix=pymupdf.Matrix(2, 2), alpha=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(path))
    except Exception:  # noqa: BLE001
        return None
    asset_id = path.stem
    return VisualAsset(
        role=role,  # type: ignore[arg-type]
        option_label=option_label,
        page=image.page,
        bounding_box=image.bbox,
        path=str(path).replace("\\", "/"),
        mime_type="image/png",
        asset_id=asset_id,
    )


def _clip_rect(page, bbox: BoundingBox):
    import pymupdf

    rect = pymupdf.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1)
    clipped = rect & page.rect
    if clipped.is_empty or clipped.width < 4 or clipped.height < 4:
        return None
    return clipped


def _visual_with_assets(visual: VisualExpectation, assets: list[VisualAsset]) -> VisualExpectation:
    if not visual.required and not assets:
        return visual
    pending = visual.required and not assets
    return VisualExpectation(
        required=visual.required or bool(assets),
        extraction_pending=pending,
        assets=assets,
    )
