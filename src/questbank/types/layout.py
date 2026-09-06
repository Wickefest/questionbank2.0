from __future__ import annotations

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float

    def union(self, other: BoundingBox) -> BoundingBox:
        return BoundingBox(
            x0=min(self.x0, other.x0),
            y0=min(self.y0, other.y0),
            x1=max(self.x1, other.x1),
            y1=max(self.y1, other.y1),
        )

    def overlaps(self, other: BoundingBox, padding: float = 0.0) -> bool:
        return not (
            self.x1 + padding < other.x0
            or other.x1 + padding < self.x0
            or self.y1 + padding < other.y0
            or other.y1 + padding < self.y0
        )

    def width(self) -> float:
        return self.x1 - self.x0

    def height(self) -> float:
        return self.y1 - self.y0

    def area(self) -> float:
        return max(0.0, self.width()) * max(0.0, self.height())

    def intersection_area(self, other: BoundingBox) -> float:
        x0 = max(self.x0, other.x0)
        y0 = max(self.y0, other.y0)
        x1 = min(self.x1, other.x1)
        y1 = min(self.y1, other.y1)
        if x1 <= x0 or y1 <= y0:
            return 0.0
        return (x1 - x0) * (y1 - y0)

    def contains_point(self, x: float, y: float, padding: float = 0.0) -> bool:
        return (
            self.x0 - padding <= x <= self.x1 + padding
            and self.y0 - padding <= y <= self.y1 + padding
        )


class TextLine(BaseModel):
    text: str
    page: int
    bbox: BoundingBox
    block_index: int
    line_index: int
    font_size: float = 0.0
    flags: int = 0
    reading_order: int | None = None

    @property
    def x0(self) -> float:
        return self.bbox.x0

    @property
    def y0(self) -> float:
        return self.bbox.y0

    @property
    def x1(self) -> float:
        return self.bbox.x1

    @property
    def y1(self) -> float:
        return self.bbox.y1


class ImageRegion(BaseModel):
    page: int
    bbox: BoundingBox
    block_index: int


class TableRegion(BaseModel):
    page: int
    bbox: BoundingBox
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    row_count: int = 0
    col_count: int = 0


class PageLayout(BaseModel):
    page_number: int
    width: float
    height: float
    raw_text: str = ""
    used_ocr: bool = False
    lines: list[TextLine] = Field(default_factory=list)
    images: list[ImageRegion] = Field(default_factory=list)
    tables: list[TableRegion] = Field(default_factory=list)


class PaperLayout(BaseModel):
    pages: list[PageLayout] = Field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def lines_in_reading_order(self) -> list[TextLine]:
        lines: list[TextLine] = []
        for page in self.pages:
            lines.extend(page.lines)
        if any(line.reading_order is not None for line in lines):
            return sorted(
                lines,
                key=lambda line: (
                    line.page,
                    line.reading_order if line.reading_order is not None else 10_000_000,
                    line.y0,
                    line.x0,
                ),
            )
        return sorted(lines, key=lambda line: (line.page, line.y0, line.x0, line.block_index))

    def images_on_page(self, page_number: int) -> list[ImageRegion]:
        for page in self.pages:
            if page.page_number == page_number:
                return page.images
        return []

    def tables_on_page(self, page_number: int) -> list[TableRegion]:
        for page in self.pages:
            if page.page_number == page_number:
                return page.tables
        return []
