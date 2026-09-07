"""Convert Gemini 0–1000 normalized boxes to pixel crops."""

from __future__ import annotations

from pathlib import Path

from questbank.types.canonical import NormBBox


def norm_bbox_to_pixels(
    bbox: list[float] | tuple[float, ...] | NormBBox,
    *,
    width: int,
    height: int,
    padding: int = 2,
) -> tuple[int, int, int, int]:
    """Return PIL crop box (left, upper, right, lower) in pixel coords."""
    if isinstance(bbox, NormBBox):
        ymin, xmin, ymax, xmax = bbox.as_list()
    else:
        if len(bbox) != 4:
            raise ValueError(f"Expected 4 bbox values, got {len(bbox)}")
        ymin, xmin, ymax, xmax = (float(v) for v in bbox)

    left = int(round((xmin / 1000.0) * width)) - padding
    upper = int(round((ymin / 1000.0) * height)) - padding
    right = int(round((xmax / 1000.0) * width)) + padding
    lower = int(round((ymax / 1000.0) * height)) + padding

    left = max(0, min(left, width - 1))
    upper = max(0, min(upper, height - 1))
    right = max(left + 1, min(right, width))
    lower = max(upper + 1, min(lower, height))
    return left, upper, right, lower


def crop_norm_bbox(
    page_image,
    bbox: list[float] | tuple[float, ...] | NormBBox,
    *,
    padding: int = 2,
):
    """Crop a PIL image using a Gemini normalized bbox."""
    width, height = page_image.size
    box = norm_bbox_to_pixels(bbox, width=width, height=height, padding=padding)
    return page_image.crop(box)


def save_crop(
    page_image,
    bbox: list[float] | tuple[float, ...] | NormBBox,
    *,
    dest: str | Path,
    padding: int = 2,
) -> Path:
    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    cropped = crop_norm_bbox(page_image, bbox, padding=padding)
    cropped.save(path, format="PNG")
    return path


__all__ = ["crop_norm_bbox", "norm_bbox_to_pixels", "save_crop"]
