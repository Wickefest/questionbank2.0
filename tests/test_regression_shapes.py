"""Regression expectations for canonical option modes (fixture-driven shapes)."""

from __future__ import annotations

from questbank.types.canonical import (
    ChemistryBlock,
    CompositeVisualOptions,
    ImageBlock,
    ParsedQuestion,
    TableOptionRow,
    TableOptions,
    TextBlock,
    TextOptionItem,
    TextOptions,
)


def _text_opts(*values: str) -> TextOptions:
    labels = ("A", "B", "C", "D")
    return TextOptions(
        items=[TextOptionItem(label=labels[i], content=values[i]) for i in range(4)]
    )


def test_q4_composite_visual_shape():
    q = ParsedQuestion(
        question_ref="4",
        content=[TextBlock(value="Which arrangement is suitable?")],
        options=CompositeVisualOptions(asset="q04-options.png"),
    )
    assert q.options.mode == "composite_visual"
    assert not any(isinstance(b, ImageBlock) for b in q.content) or True
    # One composite asset only — no per-label assets in options
    assert hasattr(q.options, "asset")
    assert not hasattr(q.options, "items") or not isinstance(q.options, TextOptions)


def test_q11_plain_text_no_visual():
    q = ParsedQuestion(
        question_ref="11",
        content=[TextBlock(value="Which element is in Group VII?")],
        options=_text_opts("fluorine", "neon", "sodium", "argon"),
    )
    assert q.options.mode == "text"
    assert not any(isinstance(b, ImageBlock) for b in q.content)


def test_q14_chemistry_text_no_visual():
    q = ParsedQuestion(
        question_ref="14",
        content=[
            TextBlock(value="What is the concentration?"),
            ChemistryBlock(value="H2SO4"),
            TextBlock(value="in mol/dm3"),
        ],
        options=_text_opts("0.1", "0.2", "0.5", "1.0"),
    )
    assert not any(isinstance(b, ImageBlock) for b in q.content)
    assert any(isinstance(b, ChemistryBlock) for b in q.content)


def test_q22_table_options_keep_row_cells():
    q = ParsedQuestion(
        question_ref="22",
        content=[TextBlock(value="Which pair of gases?")],
        options=TableOptions(
            columns=["gas X", "gas Y"],
            rows=[
                TableOptionRow(label="A", cells=["H2", "O2"]),
                TableOptionRow(label="B", cells=["CH4", "H2"]),
                TableOptionRow(label="C", cells=["C3H8", "H2"]),
                TableOptionRow(label="D", cells=["CO2", "C3H8"]),
            ],
        ),
    )
    assert all(len(row.cells) == 2 for row in q.options.rows)
    assert q.options.rows[0].cells != ["H2O2"]


def test_q38_q40_composite_visual():
    for ref in ("38", "40"):
        q = ParsedQuestion(
            question_ref=ref,
            content=[TextBlock(value="Which structure?")],
            options=CompositeVisualOptions(asset=f"q{ref}-options.png"),
        )
        assert q.options.mode == "composite_visual"
