from __future__ import annotations

from questbank.parsers.chemistry.content_blocks import (
    attach_visual_paths_to_content,
    build_mcq_content,
)
from questbank.types.layout import BoundingBox
from questbank.types.question import (
    ContentBlock,
    ParsedOption,
    VisualAsset,
)

def test_build_mcq_content_preserves_order_from_model():
    options = {
        label: ParsedOption(label=label, text=None, requires_visual=True)
        for label in ("A", "B", "C", "D")
    }
    blocks = build_mcq_content(
        stem="Which structure?",
        options=options,
        raw_blocks=[
            {"type": "text", "text": "The graph shows how yield changes with pressure."},
            {"type": "diagram", "requires_visual": True},
            {"type": "text", "text": "Which option is correct?"},
            {"type": "options", "requires_visual": True},
        ],
        tables=[],
        has_diagram=True,
    )
    assert [block.type for block in blocks] == ["text", "diagram", "text", "options"]
    assert "yield changes" in (blocks[0].text or "")
    assert blocks[3].requires_visual is True


def test_build_mcq_content_drops_placeholders_and_figure_labels():
    options = {
        label: ParsedOption(label=label, text="oxygen", requires_visual=False)
        for label in ("A", "B", "C", "D")
    }
    blocks = build_mcq_content(
        stem="Refer to the electrolytic set-up.",
        options=options,
        raw_blocks=[
            {"type": "text", "text": "intro text before any diagram"},
            {"type": "diagram", "requires_visual": True},
            {"type": "text", "text": "molten zinc bromide"},
            {"type": "text", "text": "What will be observed after a few minutes?"},
            {"type": "options", "requires_visual": False},
        ],
        tables=[],
        has_diagram=True,
    )
    texts = [block.text for block in blocks if block.type == "text"]
    assert "intro text before any diagram" not in texts
    assert "molten zinc bromide" not in texts
    assert any(text and "observed" in text for text in texts)


def test_build_mcq_content_drops_option_leaks_and_extra_diagrams():
    options = {
        "A": ParsedOption(label="A", text="1, 2, 3 and 4", requires_visual=False),
        "B": ParsedOption(label="B", text="1, 4 and 6", requires_visual=False),
        "C": ParsedOption(label="C", text="1, 5 and 6", requires_visual=False),
        "D": ParsedOption(label="D", text="2, 4, 5 and 6", requires_visual=False),
    }
    blocks = build_mcq_content(
        stem="A student is given saturated solutions.",
        options=options,
        raw_blocks=[
            {"type": "text", "text": "Which apparatus must she use?"},
            {"type": "diagram", "requires_visual": True},
            {"type": "diagram", "requires_visual": True},
            {"type": "text", "text": "A 1, 2, 3 and 4"},
            {"type": "text", "text": "D 2, 4, 5 and 6"},
            {
                "type": "text",
                "text": "A ammonium chloride B copper(II) carbonate C phosphorus pentachloride D sodium nitrate",
            },
        ],
        tables=[],
        has_diagram=True,
    )
    assert [block.type for block in blocks] == ["text", "diagram", "options"]
    texts = [block.text for block in blocks if block.type == "text"]
    assert texts == ["Which apparatus must she use?"]


def test_attach_visual_paths_maps_stem_and_single_options_crop():
    content = build_mcq_content(
        stem="diagram then options",
        options={
            label: ParsedOption(label=label, text=None, requires_visual=True)
            for label in ("A", "B", "C", "D")
        },
        raw_blocks=[
            {"type": "diagram"},
            {"type": "options", "requires_visual": True},
        ],
        tables=[],
        has_diagram=True,
    )
    assets = [
        VisualAsset(
            role="stem",
            option_label=None,
            page=1,
            bounding_box=BoundingBox(x0=1, y0=1, x1=10, y1=10),
            path="output/q01-stem.png",
        ),
        VisualAsset(
            role="option",
            option_label=None,
            page=1,
            bounding_box=BoundingBox(x0=1, y0=20, x1=40, y1=50),
            path="output/q01-options.png",
        ),
    ]
    updated = attach_visual_paths_to_content(content, assets)
    assert updated[0].asset_path == "output/q01-stem.png"
    assert updated[1].asset_path == "output/q01-options.png"


def test_attach_drops_orphan_diagram_without_asset():
    content = [
        ContentBlock(type="diagram", requires_visual=True),
        ContentBlock(type="diagram", requires_visual=True),
        ContentBlock(type="text", text="What is observed?"),
    ]
    assets = [
        VisualAsset(
            role="stem",
            option_label=None,
            page=1,
            bounding_box=BoundingBox(x0=1, y0=1, x1=10, y1=10),
            path="output/q39-stem.png",
        ),
    ]
    updated = attach_visual_paths_to_content(content, assets)
    assert [block.type for block in updated] == ["diagram", "text"]
    assert updated[0].asset_path == "output/q39-stem.png"
