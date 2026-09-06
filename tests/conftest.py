from __future__ import annotations

from pathlib import Path

import pytest

from questbank.types.layout import BoundingBox, ImageRegion, PageLayout, PaperLayout, TableRegion, TextLine

REPO_ROOT = Path(__file__).resolve().parents[1]
CHEM_PAPER_PDF = REPO_ROOT / "Chem Paper.pdf"


def line(
    text: str,
    page: int = 1,
    x0: float = 101.3,
    y0: float = 100.0,
    x1: float | None = None,
    y1: float | None = None,
    block_index: int = 0,
    line_index: int = 0,
) -> TextLine:
    return TextLine(
        text=text,
        page=page,
        bbox=BoundingBox(x0=x0, y0=y0, x1=x1 if x1 is not None else x0 + max(12, 6 * len(text)), y1=y1 or y0 + 12),
        block_index=block_index,
        line_index=line_index,
    )


def qnum(number: int, page: int = 1, y0: float = 80.0, isolated: bool = True, stem: str = "") -> TextLine:
    if isolated:
        return line(str(number), page=page, x0=77.2, y0=y0, x1=87.2, block_index=number)
    return line(f"{number} {stem}", page=page, x0=77.2, y0=y0, x1=400, block_index=number)


def paper_from_lines(
    lines: list[TextLine],
    images: list[ImageRegion] | None = None,
    tables: list[TableRegion] | None = None,
    pages: int | None = None,
) -> PaperLayout:
    page_count = pages or max((item.page for item in lines), default=1)
    grouped: dict[int, list[TextLine]] = {index: [] for index in range(1, page_count + 1)}
    for item in lines:
        grouped.setdefault(item.page, []).append(item)
    image_map: dict[int, list[ImageRegion]] = {}
    for image in images or []:
        image_map.setdefault(image.page, []).append(image)
    table_map: dict[int, list[TableRegion]] = {}
    for table in tables or []:
        table_map.setdefault(table.page, []).append(table)
    return PaperLayout(
        pages=[
            PageLayout(
                page_number=index,
                width=595.3,
                height=841.9,
                raw_text="\n".join(item.text for item in grouped.get(index, [])),
                lines=grouped.get(index, []),
                images=image_map.get(index, []),
                tables=table_map.get(index, []),
            )
            for index in range(1, page_count + 1)
        ]
    )


@pytest.fixture
def chem_paper_pdf() -> Path:
    if not CHEM_PAPER_PDF.exists():
        pytest.skip("Chem Paper.pdf is not in the workspace")
    return CHEM_PAPER_PDF
