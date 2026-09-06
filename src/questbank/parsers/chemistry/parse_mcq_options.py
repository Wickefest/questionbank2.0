from __future__ import annotations

import re
from dataclasses import dataclass

from questbank.types.layout import BoundingBox, ImageRegion, TextLine
from questbank.types.question import OPTION_LABELS, OptionLabel, ParsedOption

_OPTION_LABEL_X_MAX = 120.0
_SAME_ROW_Y = 16.0
_GRID_X_GAP = 80.0
# Stem sentences like "A student is given..." — not short option phrases like "A ammonium chloride".
_ARTICLE_SENTENCE = re.compile(
    r"^A\s+[a-z][a-z\-]*\s+"
    r"(?:is|are|was|were|has|have|had|can|could|will|would|must|should|"
    r"consists|contains|burns|reacts|forms|does|did|of|with|from|to)\b",
    re.I,
)
_LEADING_LABEL = re.compile(r"^([A-D])(?:[\.\)]\s*|\s+)(\S.*)$")
_INLINE_LABEL = re.compile(r"(?:^|(?<=\s))([B-D])(?:[\.\)]\s*|\s+)(?=\S)")
_TRAILING_LABEL = re.compile(r"(?:^|(?<=\s))([A-D])\s*$")


@dataclass(frozen=True)
class OptionMarker:
    label: OptionLabel
    line: TextLine
    text_after: str
    x0: float
    y0: float


def find_option_run(
    lines: list[TextLine],
    question_number_line: TextLine,
) -> list[OptionMarker] | None:
    return _best_option_run(_option_markers(lines, question_number_line))


def parse_mcq_options(
    lines: list[TextLine],
    images: list[ImageRegion],
    question_number_line: TextLine,
) -> dict[OptionLabel, ParsedOption]:
    markers = find_option_run(lines, question_number_line)
    if markers is None:
        return {
            label: ParsedOption(label=label, text=None, requires_visual=False)
            for label in OPTION_LABELS
        }

    texts = _option_texts(markers, lines, images)
    options: dict[OptionLabel, ParsedOption] = {}
    for label in OPTION_LABELS:
        marker = next((item for item in markers if item.label == label), None)
        raw = texts.get(label)
        visual = _option_requires_visual(marker, raw, images, markers)
        if visual:
            options[label] = ParsedOption(label=label, text=None, requires_visual=True)
        else:
            options[label] = ParsedOption(label=label, text=raw, requires_visual=False)
    return options


def _option_markers(lines: list[TextLine], question_number_line: TextLine) -> list[OptionMarker]:
    markers: list[OptionMarker] = []
    for line in lines:
        if _same_line(line, question_number_line):
            continue
        markers.extend(_markers_on_line(line))
    return markers


def _markers_on_line(line: TextLine) -> list[OptionMarker]:
    text = line.text.strip()
    if text in OPTION_LABELS:
        return [
            OptionMarker(
                label=text,  # type: ignore[arg-type]
                line=line,
                text_after="",
                x0=line.x0,
                y0=line.y0,
            )
        ]

    markers: list[OptionMarker] = []
    leading = _LEADING_LABEL.match(text)
    if leading and not _is_english_article(leading.group(1), leading.group(2), line.x0):
        label = leading.group(1)
        rest = leading.group(2)
        inline = list(_INLINE_LABEL.finditer(rest))
        if inline:
            first = inline[0]
            a_text = rest[: first.start()].strip()
            markers.append(
                OptionMarker(
                    label=label,  # type: ignore[arg-type]
                    line=line,
                    text_after=a_text,
                    x0=line.x0,
                    y0=line.y0,
                )
            )
            for match in inline:
                after = rest[match.end() :].strip()
                next_inline = None
                for other in inline:
                    if other.start() > match.start():
                        next_inline = other
                        break
                if next_inline is not None:
                    after = rest[match.end() : next_inline.start()].strip()
                markers.append(
                    OptionMarker(
                        label=match.group(1),  # type: ignore[arg-type]
                        line=line,
                        text_after=after,
                        x0=line.x0
                        + (match.start(1) / max(len(rest), 1)) * max(line.bbox.width(), 1),
                        y0=line.y0,
                    )
                )
            return markers

        rest, extra = _split_trailing_labels(rest, line)
        markers.append(
            OptionMarker(
                label=label,  # type: ignore[arg-type]
                line=line,
                text_after=rest.strip(),
                x0=line.x0,
                y0=line.y0,
            )
        )
        markers.extend(extra)
        return markers

    for match in _INLINE_LABEL.finditer(text):
        label = match.group(1)
        after = text[match.end() :].strip()
        after, extra = _split_trailing_labels(after, line)
        markers.append(
            OptionMarker(
                label=label,  # type: ignore[arg-type]
                line=line,
                text_after=after,
                x0=line.x0 + (match.start(1) / max(len(text), 1)) * max(line.bbox.width(), 1),
                y0=line.y0,
            )
        )
        markers.extend(extra)
    return markers


def _split_trailing_labels(text: str, line: TextLine) -> tuple[str, list[OptionMarker]]:
    extras: list[OptionMarker] = []
    working = text
    trailing = _TRAILING_LABEL.search(working)
    if trailing and trailing.group(1) in OPTION_LABELS and trailing.start() > 0:
        label = trailing.group(1)
        working = working[: trailing.start()].strip()
        extras.append(
            OptionMarker(
                label=label,  # type: ignore[arg-type]
                line=line,
                text_after="",
                x0=line.x1,
                y0=line.y0,
            )
        )
    return working, extras


def _is_english_article(label: str, rest: str, x0: float) -> bool:
    if label != "A":
        return False
    if x0 > _OPTION_LABEL_X_MAX:
        return True
    # Require a stem-like continuation ("A student is...", "A sample of...").
    # Short options such as "A ammonium chloride" must stay as option A.
    return bool(_ARTICLE_SENTENCE.match(f"A {rest}"))


def _best_option_run(markers: list[OptionMarker]) -> list[OptionMarker] | None:
    best: list[OptionMarker] = []
    index = 0
    while index < len(markers):
        if markers[index].label != "A":
            index += 1
            continue
        run = [markers[index]]
        expected = "B"
        look = index + 1
        while look < len(markers) and markers[look].label == expected and expected <= "D":
            run.append(markers[look])
            expected = chr(ord(expected) + 1)
            look += 1
        if len(run) >= 2 and (len(run) > len(best) or (len(run) == len(best) and run[0].y0 >= best[0].y0)):
            best = run
        index = look if look > index + 1 else index + 1
    return best or None


def _option_texts(
    markers: list[OptionMarker],
    lines: list[TextLine],
    images: list[ImageRegion],
) -> dict[OptionLabel, str | None]:
    layout = _classify_option_layout(markers)
    texts: dict[OptionLabel, str | None] = {}
    for index, marker in enumerate(markers):
        nxt = markers[index + 1] if index + 1 < len(markers) else None
        if layout == "grid":
            pieces = _grid_cell_text(marker, nxt, markers, lines, images)
        elif layout == "horizontal":
            pieces = [marker.text_after] if marker.text_after else []
            pieces.extend(_horizontal_text(marker, nxt, lines, images))
        else:
            pieces = [marker.text_after] if marker.text_after else []
            pieces.extend(_vertical_text(marker, nxt, lines, images))
        joined = _join_option_pieces(pieces)
        texts[marker.label] = joined or None
    return texts


def _classify_option_layout(markers: list[OptionMarker]) -> str:
    by_label = {marker.label: marker for marker in markers}
    a, b, c, d = (by_label.get(label) for label in OPTION_LABELS)
    if a and b and c and d:
        if abs(a.y0 - b.y0) <= _SAME_ROW_Y and abs(c.y0 - d.y0) <= _SAME_ROW_Y:
            if b.x0 - a.x0 >= _GRID_X_GAP and abs(a.y0 - c.y0) > _SAME_ROW_Y:
                return "grid"
        ys = [marker.y0 for marker in markers]
        if max(ys) - min(ys) <= _SAME_ROW_Y:
            return "horizontal"
    return "vertical"


def _vertical_text(
    marker: OptionMarker,
    nxt: OptionMarker | None,
    lines: list[TextLine],
    images: list[ImageRegion],
) -> list[str]:
    pieces: list[str] = []
    row_slack = 12.0
    start_key = (marker.line.page, marker.y0 - row_slack, 0.0)
    if nxt:
        end_key = (nxt.line.page, nxt.y0 - row_slack, 10_000.0)
    else:
        end_key = (10_000, 10_000, 10_000)
    for line in lines:
        key = (line.page, line.y0, line.x0)
        if key < start_key:
            continue
        if key >= end_key:
            continue
        if _same_line(line, marker.line):
            # text_after already captured inline content from this line
            continue
        if _is_option_label_line(line):
            continue
        if is_image_annotation(line, images):
            continue
        pieces.append(line.text.strip())
    return pieces


def _horizontal_text(
    marker: OptionMarker,
    nxt: OptionMarker | None,
    lines: list[TextLine],
    images: list[ImageRegion],
) -> list[str]:
    x_end = nxt.x0 - 4 if nxt and abs(nxt.y0 - marker.y0) <= _SAME_ROW_Y else 10_000
    pieces: list[str] = []
    for line in lines:
        if abs(line.y0 - marker.y0) > _SAME_ROW_Y:
            continue
        if line.x0 < marker.x0 - 1:
            continue
        if line.x0 >= x_end:
            continue
        if _same_line(line, marker.line):
            continue
        if line.text.strip() in OPTION_LABELS:
            continue
        if is_image_annotation(line, images):
            continue
        pieces.append(line.text.strip())
    return pieces


def _grid_cell_text(
    marker: OptionMarker,
    nxt: OptionMarker | None,
    markers: list[OptionMarker],
    lines: list[TextLine],
    images: list[ImageRegion],
) -> list[str]:
    del nxt
    by_label = {item.label: item for item in markers}
    xs = sorted({item.x0 for item in markers})
    ys = sorted({item.y0 for item in markers})
    col = 0 if marker.x0 <= (xs[0] + xs[-1]) / 2 else 1
    row = 0 if marker.y0 <= (ys[0] + ys[-1]) / 2 else 1
    x0 = xs[0] - 10
    x1 = (xs[0] + xs[-1]) / 2 + 20 if col == 0 else 10_000
    if col == 1:
        x0 = (xs[0] + xs[-1]) / 2
    y0 = marker.y0 - 6
    lower = by_label.get("C") or by_label.get("D")
    y1 = (lower.y0 - 8) if row == 0 and lower else marker.y0 + 140
    pieces: list[str] = []
    for line in lines:
        if line.page != marker.line.page:
            continue
        if line.x0 < x0 or line.x0 > x1:
            continue
        if line.y0 < y0 or line.y0 > y1:
            continue
        if line.text.strip() in OPTION_LABELS:
            continue
        if is_image_annotation(line, images):
            continue
        pieces.append(line.text.strip())
    return pieces


def _option_requires_visual(
    marker: OptionMarker | None,
    text: str | None,
    images: list[ImageRegion],
    markers: list[OptionMarker],
) -> bool:
    if _classify_option_layout(markers) == "grid":
        return True
    if marker is None:
        return False
    if text and text.strip():
        return False
    return _images_near(marker, images)


def _images_near(marker: OptionMarker, images: list[ImageRegion]) -> bool:
    probe = BoundingBox(x0=marker.x0, y0=marker.y0, x1=marker.x0 + 220, y1=marker.y0 + 140)
    return any(image.page == marker.line.page and image.bbox.overlaps(probe, 8) for image in images)


def is_image_annotation(line: TextLine, images: list[ImageRegion]) -> bool:
    words = line.text.strip().split()
    if len(words) > 4:
        return False
    return any(
        image.page == line.page and image.bbox.overlaps(line.bbox, 12) for image in images
    )


def _is_option_label_line(line: TextLine) -> bool:
    return line.text.strip() in OPTION_LABELS


def _same_line(left: TextLine, right: TextLine) -> bool:
    return (
        left.page == right.page
        and left.block_index == right.block_index
        and left.line_index == right.line_index
        and abs(left.y0 - right.y0) < 1.0
        and abs(left.x0 - right.x0) < 1.0
    )


def _line_at_or_after_marker(line: TextLine, marker: OptionMarker) -> bool:
    if marker.line.page and line.page > marker.line.page:
        return True
    if line.page < marker.line.page:
        return False
    if line.y0 > marker.y0 + 2:
        return True
    return abs(line.y0 - marker.y0) <= _SAME_ROW_Y and line.x0 >= marker.x0 - 1


def _join_option_pieces(pieces: list[str]) -> str:
    cleaned = [re.sub(r"[ \t]+", " ", piece).strip() for piece in pieces if piece and piece.strip()]
    if not cleaned:
        return ""
    joined = " ".join(cleaned)
    return _collapse_repeated_option_text(joined)


def _collapse_repeated_option_text(text: str) -> str:
    collapsed = _collapse_repeated_phrase(text)
    # Docling inline options sometimes become: "1, 2, 3 and 4 A 1, 2, 3 and 4"
    for label in OPTION_LABELS:
        pattern = re.compile(
            rf"^(?P<body>.+?)\s+{label}\s+(?P=body)$",
            re.I,
        )
        match = pattern.match(collapsed)
        if match:
            return match.group("body").strip()
    return collapsed


def _collapse_repeated_phrase(text: str) -> str:
    parts = text.split()
    if len(parts) < 6:
        return text
    for size in range(len(parts) // 2, 2, -1):
        if parts[:size] == parts[size : 2 * size]:
            return " ".join(parts[:size])
    return text
