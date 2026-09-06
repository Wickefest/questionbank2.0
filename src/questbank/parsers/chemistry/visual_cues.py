from __future__ import annotations

import re

VISUAL_PATTERNS = (
    re.compile(r"diagram below", re.I),
    re.compile(r"diagram shows", re.I),
    re.compile(r"\bthe diagram\b", re.I),
    re.compile(r"graph below", re.I),
    re.compile(r"graph shows", re.I),
    re.compile(r"\bthe graph\b", re.I),
    re.compile(r"into a graph", re.I),
    re.compile(r"which graph", re.I),
    re.compile(r"heating curve", re.I),
    re.compile(r"apparatus shown", re.I),
    re.compile(r"set-?up shown", re.I),
    re.compile(r"set-?up below", re.I),
    re.compile(r"shown below", re.I),
    re.compile(r"\bare shown\b", re.I),
    re.compile(r"\bis shown\b", re.I),
    re.compile(r"structures?\b.{0,40}\bshown", re.I),
    re.compile(r"refer to the following set-?up", re.I),
    re.compile(r"refer to the following", re.I),
    re.compile(r"energy profile diagram", re.I),
    re.compile(r"simple cell", re.I),
)


def stem_requires_visual(stem: str) -> bool:
    return any(pattern.search(stem) for pattern in VISUAL_PATTERNS)
