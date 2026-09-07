"""Unit tests for lean canonical schemas and bbox cropping."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from questbank.pdf.bbox_crop import norm_bbox_to_pixels, save_crop
from questbank.types.canonical import (
    ChemistryBlock,
    CompositeVisualOptions,
    GeminiPageParseResult,
    ImageBlock,
    MathBlock,
    MathOptionItem,
    MathOptions,
    ParsedQuestion,
    TableBlock,
    TextBlock,
    TextOptionItem,
    TextOptions,
)


def test_text_question_schema_roundtrip():
    q = ParsedQuestion(
        question_ref="11",
        content=[TextBlock(value="Which gas is produced?")],
        options=TextOptions(
            items=[
                TextOptionItem(label="A", content="hydrogen"),
                TextOptionItem(label="B", content="oxygen"),
                TextOptionItem(label="C", content="nitrogen"),
                TextOptionItem(label="D", content="chlorine"),
            ]
        ),
    )
    dumped = q.model_dump()
    assert "stem" not in dumped
    assert "chemistry" not in dumped
    assert dumped["options"]["mode"] == "text"
    assert ParsedQuestion.model_validate(dumped).question_ref == "11"


def test_math_and_chemistry_blocks():
    q = ParsedQuestion(
        question_ref="8",
        content=[
            TextBlock(value="Which nuclide?"),
            ChemistryBlock(value="^{14}_{6}C"),
            MathBlock(latex=r"\frac{S-T}{U}"),
        ],
        options=MathOptions(
            items=[
                MathOptionItem(label="A", latex=r"\frac{S}{U}"),
                MathOptionItem(label="B", latex=r"\frac{T}{U}"),
                MathOptionItem(label="C", latex=r"\frac{S-T}{U}"),
                MathOptionItem(label="D", latex=r"\frac{S-T}{U-T}"),
            ]
        ),
    )
    assert q.content[1].type == "chemistry"
    assert q.options.mode == "math"


def test_composite_visual_options():
    q = ParsedQuestion(
        question_ref="4",
        content=[TextBlock(value="Which arrangement?")],
        options=CompositeVisualOptions(asset="q04-options.png", labels=["A", "B", "C", "D"]),
    )
    assert q.options.mode == "composite_visual"
    assert q.options.asset == "q04-options.png"


def test_stem_visual_image_block_only_when_needed():
    q = ParsedQuestion(
        question_ref="29",
        content=[
            TextBlock(value="The graph below shows..."),
            ImageBlock(asset="q29-graph.png"),
            TextBlock(value="What is the rate?"),
        ],
        options=TextOptions(
            items=[TextOptionItem(label=lbl, content=lbl) for lbl in ("A", "B", "C", "D")]
        ),
    )
    images = [b for b in q.content if isinstance(b, ImageBlock)]
    assert len(images) == 1


def test_gemini_page_schema_accepts_table_block():
    payload = {
        "questions": [
            {
                "question_ref": "7",
                "content": [
                    {"type": "text", "value": "Look at the table."},
                    {
                        "type": "table",
                        "columns": ["X", "Y"],
                        "rows": [["1", "2"], ["3", "4"]],
                    },
                ],
                "options": {
                    "mode": "text",
                    "items": [
                        {"label": "A", "content": "a"},
                        {"label": "B", "content": "b"},
                        {"label": "C", "content": "c"},
                        {"label": "D", "content": "d"},
                    ],
                },
                "stem_visuals": [],
                "requires_review": False,
            }
        ]
    }
    result = GeminiPageParseResult.model_validate(payload)
    assert isinstance(result.questions[0].content[1], TableBlock)


def test_norm_bbox_to_pixels_and_crop(tmp_path: Path):
    img = Image.new("RGB", (1000, 2000), color=(255, 255, 255))
    # box covering middle quarter
    left, upper, right, lower = norm_bbox_to_pixels(
        [250, 250, 750, 750],
        width=1000,
        height=2000,
        padding=0,
    )
    assert left == 250
    assert upper == 500  # 250/1000 * 2000
    assert right == 750
    assert lower == 1500

    path = save_crop(img, [0, 0, 500, 500], dest=tmp_path / "crop.png", padding=0)
    assert path.exists()
    cropped = Image.open(path)
    assert cropped.size == (500, 1000)
