from __future__ import annotations

from questbank.parsers.chemistry.parse_structured_vision import (
    _item_to_question,
    _merge_questions,
    _parse_json_object,
    _parse_part,
    box2d_to_pixel_box,
)
from questbank.types.question import (
    QuestionValidation,
    SourceRegion,
    VisualExpectation,
)
from questbank.types.structured import StructuredPart, StructuredQuestion


def test_box2d_to_pixel_box():
    box = box2d_to_pixel_box([100, 200, 500, 800], width=1000, height=2000)
    assert box == (200, 200, 800, 1000)


def test_parse_vision_json_object_and_fence():
    raw = """```json
{"page_title": "Ammonia Test", "is_answers_section": false, "questions": []}
```"""
    data = _parse_json_object(raw)
    assert data["page_title"] == "Ammonia Test"
    assert data["questions"] == []


def test_item_to_question_maps_parts(tmp_path):
    from PIL import Image

    image = Image.new("RGB", (1000, 1400), color=(255, 255, 255))
    item = {
        "question_number": 2,
        "box_2d": [50, 40, 900, 960],
        "stem": "Ammonia is prepared industrially.",
        "marks_total": 4,
        "has_diagram": True,
        "parts": [
            {
                "label": "a",
                "prompt": "Read the graph.",
                "marks": 1,
                "children": [],
            },
            {
                "label": "b",
                "prompt": "Exothermic or endothermic?",
                "marks": 2,
                "children": [
                    {"label": "i", "prompt": "Explain.", "marks": 1, "children": []}
                ],
            },
        ],
    }
    question = _item_to_question(
        item,
        page_number=3,
        page_image=image,
        page_width=1000,
        page_height=1400,
        visuals_dir=tmp_path,
    )
    assert question.question_number == 2
    assert "industrially" in question.stem
    assert question.parts[0].label == "a"
    assert question.parts[1].children[0].label == "i"
    assert question.visual.assets
    assert (tmp_path / "q02-p03-vision.png").exists()


def test_merge_questions_appends_continuation_parts():
    left = StructuredQuestion(
        question_number=1,
        source=SourceRegion(page_start=1, page_end=1, bounding_box=None),
        stem="Intro",
        parts=[StructuredPart(label="a", prompt="Part a", marks=1)],
        visual=VisualExpectation(required=False, extraction_pending=False),
        validation=QuestionValidation(status="pass", issues=[]),
    )
    right = StructuredQuestion(
        question_number=1,
        source=SourceRegion(page_start=2, page_end=2, bounding_box=None),
        stem="",
        parts=[StructuredPart(label="b", prompt="Part b", marks=2)],
        visual=VisualExpectation(required=False, extraction_pending=False),
        validation=QuestionValidation(status="pass", issues=[]),
    )
    merged = _merge_questions(left, right)
    assert merged.source.page_end == 2
    assert [part.label for part in merged.parts] == ["a", "b"]


def test_parse_part_nested():
    part = _parse_part(
        {
            "label": "A",
            "prompt": "Parent",
            "marks": 2,
            "children": [{"label": "ii", "prompt": "Child", "marks": 1, "children": []}],
        }
    )
    assert part.label == "a"
    assert part.children[0].label == "ii"
