from __future__ import annotations

from questbank.pdf.extract_visuals import (
    assign_images_to_questions,
    build_slice_bands,
    promote_visual_options,
    _merge_image_regions,
)
from questbank.types.layout import BoundingBox, ImageRegion
from questbank.types.question import (
    ParsedOption,
    ParsedQuestion,
    SourceRegion,
    VisualExpectation,
)


def test_band_assignment_includes_option_diagram_below_stem_text():
    """Option grids often sit below the last OCR line of the stem."""
    bands = build_slice_bands(
        [
            (3, 3, 60.0),
            (4, 3, 377.0),
            (5, 4, 60.0),
        ],
        final_page=4,
    )
    images = [
        ImageRegion(page=3, bbox=BoundingBox(x0=99, y0=175, x1=543, y1=288), block_index=0),
        ImageRegion(page=3, bbox=BoundingBox(x0=94, y0=471, x1=558, y1=767), block_index=1),
    ]
    assigned = assign_images_to_questions(bands, images)
    assert len(assigned[3]) == 1
    assert assigned[3][0].block_index == 0
    assert len(assigned[4]) == 1
    assert assigned[4][0].block_index == 1


def test_image_bands_prevent_cross_question_duplicates():
    bands = build_slice_bands(
        [
            (34, 13, 65.0),
            (35, 13, 427.0),
            (36, 13, 612.0),
        ],
        final_page=13,
    )
    images = [
        ImageRegion(page=13, bbox=BoundingBox(x0=120, y0=100, x1=400, y1=290), block_index=1),
        ImageRegion(page=13, bbox=BoundingBox(x0=110, y0=445, x1=510, y1=497), block_index=2),
        ImageRegion(page=13, bbox=BoundingBox(x0=150, y0=630, x1=400, y1=700), block_index=3),
    ]
    assigned = assign_images_to_questions(bands, images)
    assert len(assigned[34]) == 1
    assert assigned[34][0].block_index == 1
    assert len(assigned[35]) == 1
    assert assigned[35][0].block_index == 2
    assert len(assigned[36]) == 1
    assert assigned[36][0].block_index == 3


def test_merge_option_images_into_one_region():
    images = [
        ImageRegion(page=14, bbox=BoundingBox(x0=129, y0=522, x1=245, y1=597), block_index=1),
        ImageRegion(page=14, bbox=BoundingBox(x0=362, y0=522, x1=501, y1=603), block_index=2),
        ImageRegion(page=14, bbox=BoundingBox(x0=129, y0=619, x1=254, y1=703), block_index=3),
        ImageRegion(page=14, bbox=BoundingBox(x0=362, y0=619, x1=516, y1=703), block_index=4),
    ]
    merged = _merge_image_regions(images)
    assert merged is not None
    assert merged.bbox.x0 == 129
    assert merged.bbox.y0 == 522
    assert merged.bbox.x1 == 516
    assert merged.bbox.y1 == 703


def test_promote_single_options_grid_without_stem_figure():
    images = [
        ImageRegion(page=3, bbox=BoundingBox(x0=100, y0=200, x1=500, y1=600), block_index=1),
    ]
    question = ParsedQuestion(
        question_number=4,
        source=SourceRegion(page_start=3, page_end=3, bounding_box=None),
        stem="Which arrangement is suitable for drying and collecting ammonia?",
        options={
            label: ParsedOption(label=label, text=None, requires_visual=False)
            for label in ("A", "B", "C", "D")
        },
        visual=VisualExpectation(required=False, extraction_pending=False),
        validation={"status": "pass", "issues": []},
    )
    updated, remapped = promote_visual_options(question, images)
    assert all(updated.options[label].requires_visual for label in ("A", "B", "C", "D"))
    assert len(remapped) == 1


def test_promote_does_not_turn_stem_apparatus_into_options():
    images = [
        ImageRegion(page=4, bbox=BoundingBox(x0=100, y0=100, x1=400, y1=300), block_index=1),
    ]
    question = ParsedQuestion(
        question_number=6,
        source=SourceRegion(page_start=4, page_end=4, bounding_box=None),
        stem="A mixture is heated using the set-up shown. Which mixture can be separated?",
        options={
            label: ParsedOption(label=label, text=None, requires_visual=False)
            for label in ("A", "B", "C", "D")
        },
        visual=VisualExpectation(required=False, extraction_pending=False),
        validation={"status": "pass", "issues": []},
    )
    updated, remapped = promote_visual_options(question, images)
    assert all(not updated.options[label].requires_visual for label in ("A", "B", "C", "D"))
    assert remapped == images


def test_promote_stem_above_structure_options_grid():
    """Polymer stem figure + A–D structure grid below → options.png, not stem-2."""
    images = [
        ImageRegion(page=15, bbox=BoundingBox(x0=207, y0=307, x1=435, y1=396), block_index=0),
        ImageRegion(page=15, bbox=BoundingBox(x0=100, y0=446, x1=451, y1=605), block_index=1),
    ]
    # Visual structure scraps as options → mark requires_visual before promote.
    question = ParsedQuestion(
        question_number=40,
        source=SourceRegion(page_start=15, page_end=15, bounding_box=None),
        stem="A section of a polymer is shown below.",
        options={
            "A": ParsedOption(label="A", text=None, requires_visual=True),
            "B": ParsedOption(label="B", text=None, requires_visual=True),
            "C": ParsedOption(label="C", text=None, requires_visual=True),
            "D": ParsedOption(label="D", text=None, requires_visual=True),
        },
        visual=VisualExpectation(required=True, extraction_pending=True),
        validation={"status": "pass", "issues": []},
    )
    updated, remapped = promote_visual_options(question, images)
    assert all(updated.options[label].requires_visual for label in ("A", "B", "C", "D"))
    assert len(remapped) == 2
    assert remapped[0].block_index == 0
    assert remapped[1].bbox.y0 == 446


def test_promote_label_echo_options_as_visual_grid():
    images = [
        ImageRegion(page=3, bbox=BoundingBox(x0=100, y0=300, x1=520, y1=620), block_index=1),
    ]
    question = ParsedQuestion(
        question_number=4,
        source=SourceRegion(page_start=3, page_end=3, bounding_box=None),
        stem="A student is provided with two drying agents.",
        options={
            "A": ParsedOption(label="A", text="dry", requires_visual=False),
            "B": ParsedOption(label="B", text="B", requires_visual=False),
            "C": ParsedOption(label="C", text="C", requires_visual=False),
            "D": ParsedOption(label="D", text="D", requires_visual=False),
        },
        visual=VisualExpectation(required=False, extraction_pending=False),
        validation={"status": "pass", "issues": []},
    )
    updated, remapped = promote_visual_options(question, images)
    assert all(updated.options[label].requires_visual for label in ("A", "B", "C", "D"))
    assert all(updated.options[label].text is None for label in ("A", "B", "C", "D"))
    assert len(remapped) == 1


def test_promote_visual_options_keeps_combined_grid():
    images = [
        ImageRegion(page=14, bbox=BoundingBox(x0=241, y0=394, x1=406, y1=497), block_index=0),
        ImageRegion(page=14, bbox=BoundingBox(x0=129, y0=522, x1=245, y1=597), block_index=1),
        ImageRegion(page=14, bbox=BoundingBox(x0=362, y0=522, x1=501, y1=603), block_index=2),
        ImageRegion(page=14, bbox=BoundingBox(x0=129, y0=619, x1=254, y1=703), block_index=3),
        ImageRegion(page=14, bbox=BoundingBox(x0=362, y0=619, x1=516, y1=703), block_index=4),
    ]
    question = ParsedQuestion(
        question_number=38,
        source=SourceRegion(page_start=14, page_end=14, bounding_box=None),
        stem="The diagram below shows the structure of propanol.",
        options={
            label: ParsedOption(label=label, text=None, requires_visual=False)
            for label in ("A", "B", "C", "D")
        },
        visual=VisualExpectation(required=False, extraction_pending=False),
        validation={"status": "pass", "issues": []},
    )
    updated, remapped = promote_visual_options(question, images)
    assert all(updated.options[label].requires_visual for label in ("A", "B", "C", "D"))
    assert len(remapped) == 2
    assert remapped[0].block_index == 0
    assert remapped[1].bbox.x0 == 129
    assert remapped[1].bbox.x1 == 516
