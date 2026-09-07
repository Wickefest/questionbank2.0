from __future__ import annotations

import re

from questbank.normalize.chemistry import normalize_chemistry_text
from questbank.types.question import (
    OPTION_LABELS,
    ContentBlock,
    ParsedOption,
    ParsedQuestion,
    ParsedTable,
    VisualAsset,
)
from questbank.types.structured import StructuredPart, StructuredQuestion

_PLACEHOLDER = re.compile(
    r"(?i)^(intro text before any diagram|question sentence after diagram|"
    r"full stem.*|option [a-d] text.*|real stem text.*|real question sentence.*|"
    r"<[^>]+>)$"
)
_OPTION_PREFIX = re.compile(r"^[A-D](?:[\.\)\:]|\s+)\s*(.+)$", re.I)
_OPTION_DUMP = re.compile(
    r"(?i)^A\s+.+\s+B\s+.+\s+C\s+.+\s+D\s+.+$"
)


def build_mcq_content(
    *,
    stem: str,
    options: dict[str, ParsedOption],
    raw_blocks: list[dict] | None,
    tables: list[ParsedTable],
    has_diagram: bool,
) -> list[ContentBlock]:
    """Build ordered content blocks; prefer model order, else infer from stem/options."""
    visual_options = all(
        options[label].requires_visual or not (options[label].text or "").strip()
        for label in OPTION_LABELS
        if label in options
    ) and len(options) == 4

    if raw_blocks:
        blocks = _blocks_from_raw(raw_blocks, tables=tables, visual_options=visual_options)
        blocks = _clean_content_blocks(
            blocks,
            stem=stem,
            has_diagram=has_diagram,
            options=options,
            visual_options=visual_options,
        )
        if blocks:
            return _ensure_options_block(blocks, options=options, visual_options=visual_options)

    blocks: list[ContentBlock] = []
    if stem.strip():
        blocks.append(ContentBlock(type="text", text=normalize_chemistry_text(stem)))
    if has_diagram:
        blocks.append(ContentBlock(type="diagram", requires_visual=True))
    for index, table in enumerate(tables):
        if table.role == "stem":
            blocks.append(ContentBlock(type="table", table_index=index, requires_visual=False))
    blocks.append(
        ContentBlock(
            type="options",
            requires_visual=visual_options,
            text=None if visual_options else _options_preview(options),
        )
    )
    return blocks


def _clean_content_blocks(
    blocks: list[ContentBlock],
    *,
    stem: str,
    has_diagram: bool,
    options: dict[str, ParsedOption] | None = None,
    visual_options: bool = False,
) -> list[ContentBlock]:
    """Drop placeholders, diagram-label crumbs, option dumps, and duplicated stem sentences."""
    cleaned: list[ContentBlock] = []
    seen_text: set[str] = set()
    stem_norm = " ".join(stem.split()).strip().lower()
    option_texts = _option_text_index(options or {})
    saw_diagram = False
    for block in blocks:
        if block.type == "diagram":
            # Keep a single diagram slot; extras are usually option-grid mislabels.
            if saw_diagram and not visual_options:
                continue
            if saw_diagram and visual_options:
                # Second "diagram" after stem is often the A–D grid → convert later via options.
                continue
            saw_diagram = True
            cleaned.append(block)
            continue
        if block.type == "text":
            text = " ".join((block.text or "").split()).strip()
            if not text or _PLACEHOLDER.match(text):
                continue
            key = text.lower()
            if key in seen_text:
                continue
            if _is_option_leak(text, option_texts):
                continue
            # Skip fragments that only repeat the full stem.
            if stem_norm and key == stem_norm:
                if any(existing.type == "text" for existing in cleaned):
                    continue
            # Skip short figure labels when a diagram exists (not real questions).
            if has_diagram and _looks_like_figure_label(text):
                continue
            if has_diagram and _looks_like_test_fragment(text):
                continue
            seen_text.add(key)
            cleaned.append(block.model_copy(update={"text": text}))
            continue
        cleaned.append(block)
    return cleaned


def _option_text_index(options: dict[str, ParsedOption]) -> set[str]:
    values: set[str] = set()
    for label, option in options.items():
        text = " ".join((option.text or "").split()).strip().lower()
        if not text:
            continue
        values.add(text)
        values.add(f"{label.lower()} {text}")
        values.add(f"{label.lower()}: {text}")
    return values


def _is_option_leak(text: str, option_texts: set[str]) -> bool:
    key = " ".join(text.split()).strip().lower()
    if key in option_texts:
        return True
    if _OPTION_DUMP.match(key):
        return True
    match = _OPTION_PREFIX.match(text.strip())
    if match:
        body = " ".join(match.group(1).split()).strip().lower()
        if body in option_texts or f"{text.strip()[0].lower()} {body}" in option_texts:
            return True
        # Lone "A 1, 2 and 3" style lines that match an option body.
        if any(body == opt or opt.endswith(body) for opt in option_texts if " " in opt or "," in opt):
            return True
    return False


def _looks_like_test_fragment(text: str) -> bool:
    """Table/test rows OCR'd as content (e.g. 'Test 3 Warming with ...')."""
    return bool(re.match(r"(?i)^test\s*\d+\b", text.strip()))


def _ensure_options_block(
    blocks: list[ContentBlock],
    *,
    options: dict[str, ParsedOption],
    visual_options: bool,
) -> list[ContentBlock]:
    if any(block.type == "options" for block in blocks):
        return blocks
    return [
        *blocks,
        ContentBlock(
            type="options",
            requires_visual=visual_options,
            text=None if visual_options else _options_preview(options),
        ),
    ]


def _looks_like_figure_label(text: str) -> bool:
    cleaned = text.strip()
    if cleaned.endswith("?"):
        return False
    words = cleaned.split()
    if len(cleaned) > 36 or len(words) > 5:
        return False
    if re.match(
        r"(?i)^(the|which|what|how|when|where|why|refer|a |an |in |from |to )",
        cleaned,
    ):
        return False
    return True


def build_structured_content(
    *,
    stem: str,
    parts: list[StructuredPart],
    raw_blocks: list[dict] | None,
    tables: list[ParsedTable],
    has_diagram: bool,
) -> list[ContentBlock]:
    if raw_blocks:
        blocks = _blocks_from_raw(raw_blocks, tables=tables, visual_options=False)
        if blocks:
            return blocks

    blocks: list[ContentBlock] = []
    if stem.strip():
        blocks.append(ContentBlock(type="text", text=normalize_chemistry_text(stem)))
    if has_diagram:
        blocks.append(ContentBlock(type="diagram", requires_visual=True))
    for index, _table in enumerate(tables):
        blocks.append(ContentBlock(type="table", table_index=index))
    for part in parts:
        prompt = normalize_chemistry_text(part.prompt) if part.prompt else ""
        if prompt:
            blocks.append(ContentBlock(type="text", text=f"({part.label}) {prompt}"))
        for child in part.children:
            child_prompt = normalize_chemistry_text(child.prompt) if child.prompt else ""
            if child_prompt:
                blocks.append(
                    ContentBlock(type="text", text=f"({part.label})({child.label}) {child_prompt}")
                )
    return blocks


def attach_visual_paths_to_content(
    content: list[ContentBlock],
    assets: list[VisualAsset],
) -> list[ContentBlock]:
    """Fill diagram/options blocks with cropped asset paths in reading order."""
    stem_paths = [asset.path for asset in assets if asset.role == "stem"]
    option_paths = [asset.path for asset in assets if asset.role == "option"]
    stem_i = 0
    updated: list[ContentBlock] = []
    for block in content:
        if block.type == "diagram" and stem_i < len(stem_paths):
            updated.append(
                block.model_copy(
                    update={"asset_path": stem_paths[stem_i], "requires_visual": True}
                )
            )
            stem_i += 1
        elif block.type == "diagram":
            # Orphan diagram slot with no remaining stem crop — drop it.
            continue
        elif block.type == "options" and option_paths:
            updated.append(
                block.model_copy(
                    update={"asset_path": option_paths[0], "requires_visual": True}
                )
            )
        else:
            updated.append(block)

    # Extra stem diagrams not declared in content (organic structures etc.)
    while stem_i < len(stem_paths):
        updated.insert(
            _insert_diagram_index(updated),
            ContentBlock(
                type="diagram",
                requires_visual=True,
                asset_path=stem_paths[stem_i],
            ),
        )
        stem_i += 1

    if option_paths:
        # Replace a trailing extra diagram with the options crop when model
        # mis-labeled the A–D structure grid as another stem diagram.
        if not any(block.type == "options" for block in updated):
            if updated and updated[-1].type == "diagram" and stem_paths:
                updated[-1] = ContentBlock(
                    type="options",
                    requires_visual=True,
                    asset_path=option_paths[0],
                )
            else:
                updated.append(
                    ContentBlock(
                        type="options",
                        requires_visual=True,
                        asset_path=option_paths[0],
                    )
                )
        else:
            for index, block in enumerate(updated):
                if block.type == "options" and not block.asset_path:
                    updated[index] = block.model_copy(
                        update={"asset_path": option_paths[0], "requires_visual": True}
                    )
    return updated


def sync_question_content_assets(question: ParsedQuestion) -> ParsedQuestion:
    content = attach_visual_paths_to_content(question.content, question.visual.assets)
    return question.model_copy(update={"content": content})


def sync_structured_content_assets(question: StructuredQuestion) -> StructuredQuestion:
    content = attach_visual_paths_to_content(question.content, question.visual.assets)
    return question.model_copy(update={"content": content})


def _blocks_from_raw(
    raw_blocks: list[dict],
    *,
    tables: list[ParsedTable],
    visual_options: bool,
) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    for raw in raw_blocks:
        if isinstance(raw, str):
            text = normalize_chemistry_text(raw.strip()) if raw.strip() else None
            if text and not _PLACEHOLDER.match(text):
                blocks.append(ContentBlock(type="text", text=text))
            continue
        if not isinstance(raw, dict):
            continue
        block_type = str(raw.get("type") or "").strip().lower()
        if block_type not in {"text", "diagram", "table", "options"}:
            continue
        text = raw.get("text")
        text = normalize_chemistry_text(str(text)) if text else None
        if text and _PLACEHOLDER.match(text.strip()):
            continue
        table_index = raw.get("table_index")
        if table_index is not None:
            try:
                table_index = int(table_index)
            except (TypeError, ValueError):
                table_index = None
        if block_type == "table" and table_index is None and tables:
            table_index = 0
        requires_visual = bool(raw.get("requires_visual"))
        if block_type == "diagram":
            requires_visual = True
        if block_type == "options" and visual_options:
            requires_visual = True
        blocks.append(
            ContentBlock(
                type=block_type,  # type: ignore[arg-type]
                text=text,
                requires_visual=requires_visual,
                table_index=table_index,
            )
        )
    return blocks


def _options_preview(options: dict[str, ParsedOption]) -> str:
    parts = []
    for label in OPTION_LABELS:
        option = options.get(label)
        if option is None:
            continue
        if option.requires_visual:
            parts.append(f"{label}: <visual>")
        elif option.text:
            parts.append(f"{label}: {option.text}")
    return "\n".join(parts)


def _insert_diagram_index(blocks: list[ContentBlock]) -> int:
    for index, block in enumerate(blocks):
        if block.type == "options":
            return index
    return len(blocks)
