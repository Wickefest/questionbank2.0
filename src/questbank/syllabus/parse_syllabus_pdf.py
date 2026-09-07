from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

_TOPIC_INLINE = re.compile(
    r"^\s*(?P<num>\d{1,2})\.\s+(?P<title>[A-Za-z].+?)\s*$"
)
_TOPIC_BARE = re.compile(r"^\s*(?P<num>\d{1,2})\.\s*$")
_SUBTOPIC_LINE = re.compile(
    r"^\s*(?P<code>\d{1,2}\.\d+)\s+(?P<title>[A-Za-z].+?)\s*$"
)
_SECTION_INLINE = re.compile(
    r"(?i)^\s*(?:SECTION\s+)?(?P<roman>[IVX]+)\.?\s*[:\-]?\s*(?P<title>.+)\s*$"
)
_SECTION_BARE = re.compile(r"^\s*(?P<roman>[IVX]+)\.\s*$")
_CONTENT_START = re.compile(r"(?i)SUBJECT\s+CONTENT")
_CONTENT_END = re.compile(
    r"(?i)SUMMARY\s+OF\s+KEY\s+QUANTITIES|PRACTICAL\s+ASSESSMENT|NOTES\s+FOR\s+QUALITATIVE"
)
_STRUCTURE_START = re.compile(r"(?i)CONTENT\s+STRUCTURE")


class SyllabusSubtopic(BaseModel):
    code: str
    title: str
    outcomes_text: str = Field(default="", serialization_alias="outcomesText")

    model_config = {"populate_by_name": True}


class SyllabusTopic(BaseModel):
    number: int
    title: str
    section: str | None = None
    subtopics: list[SyllabusSubtopic] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class SyllabusTaxonomy(BaseModel):
    syllabus_code: str = Field(default="6092", serialization_alias="syllabusCode")
    subject: str = "Chemistry"
    title: str | None = None
    topics: list[SyllabusTopic] = Field(default_factory=list)
    source_path: str | None = Field(default=None, serialization_alias="sourcePath")

    model_config = {"populate_by_name": True}

    def subtopic_count(self) -> int:
        return sum(len(topic.subtopics) for topic in self.topics)

    def iter_subtopics(self) -> list[tuple[SyllabusTopic, SyllabusSubtopic]]:
        pairs: list[tuple[SyllabusTopic, SyllabusSubtopic]] = []
        for topic in self.topics:
            for sub in topic.subtopics:
                pairs.append((topic, sub))
        return pairs


def parse_syllabus_pdf(pdf_path: str | Path) -> SyllabusTaxonomy:
    """Extract 6092 topic/subtopic taxonomy from the Chemistry syllabus PDF."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Syllabus PDF not found: {pdf_path}")

    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF is required for syllabus parsing") from exc

    chunks: list[str] = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            chunks.append(page.get_text("text") or "")
    text = "\n".join(chunks)
    taxonomy = parse_syllabus_text(text)
    taxonomy.source_path = str(pdf_path).replace("\\", "/")
    if not taxonomy.title:
        taxonomy.title = "Singapore-Cambridge GCE O-Level Chemistry (6092)"
    return taxonomy


def parse_syllabus_text(text: str) -> SyllabusTaxonomy:
    """Parse taxonomy from plain syllabus text (PDF extract or fixture)."""
    lines = [_clean_line(line) for line in text.splitlines()]
    structure_topics = _parse_content_structure(lines)
    subject_lines = _subject_content_lines(lines)
    detailed = _parse_subject_content(subject_lines)

    by_number: dict[int, SyllabusTopic] = {t.number: t for t in structure_topics}
    for topic in detailed:
        existing = by_number.get(topic.number)
        if existing is None:
            by_number[topic.number] = topic
            continue
        if topic.title and (not existing.title or len(topic.title) > len(existing.title)):
            existing.title = topic.title
        if topic.section and not existing.section:
            existing.section = topic.section
        if topic.subtopics:
            existing.subtopics = topic.subtopics

    topics = [by_number[n] for n in sorted(by_number)]
    return SyllabusTaxonomy(topics=topics)


def _clean_line(line: str) -> str:
    # PDF extracts often include odd separators / NBSP.
    return (
        (line or "")
        .replace("\u00a0", " ")
        .replace("\u2009", " ")
        .replace("\ufb01", "fi")
        .replace("\ufb02", "fl")
        .strip()
    )


def _subject_content_lines(lines: list[str]) -> list[str]:
    starts = [
        i
        for i, line in enumerate(lines)
        if re.fullmatch(r"(?i)SUBJECT\s+CONTENT", line.strip())
    ]
    if not starts:
        starts = [i for i, line in enumerate(lines) if _CONTENT_START.search(line)]
    if not starts:
        return lines
    start = starts[-1]
    end = next(
        (
            i
            for i, line in enumerate(lines[start + 1 :], start + 1)
            if re.fullmatch(r"(?i)SUMMARY\s+OF\s+KEY\s+QUANTITIES.*", line)
            or re.fullmatch(r"(?i)PRACTICAL\s+ASSESSMENT", line)
            or re.fullmatch(r"(?i)NOTES\s+FOR\s+QUALITATIVE\s+ANALYSIS", line)
        ),
        len(lines),
    )
    return lines[start:end]


def _parse_content_structure(lines: list[str]) -> list[SyllabusTopic]:
    # Prefer the standalone heading (not the TOC entry "CONTENT STRUCTURE 9").
    starts = [
        i
        for i, line in enumerate(lines)
        if re.fullmatch(r"(?i)CONTENT\s+STRUCTURE", line.strip())
    ]
    if not starts:
        starts = [i for i, line in enumerate(lines) if _STRUCTURE_START.search(line)]
    if not starts:
        return []
    start = starts[-1]
    # Stop before SUBJECT CONTENT / next major chapter.
    end = next(
        (
            i
            for i, line in enumerate(lines[start + 1 :], start + 1)
            if _CONTENT_START.search(line) or re.fullmatch(r"(?i)SUBJECT\s+CONTENT", line)
        ),
        start + 60,
    )
    block = lines[start:end]
    section: str | None = None
    topics: list[SyllabusTopic] = []
    seen: set[int] = set()
    pending_num: int | None = None
    pending_section_roman = False

    for line in block:
        if not line:
            continue
        if line.upper() in {"SECTIONS", "TOPICS", "PAGE"}:
            continue

        if _SECTION_BARE.match(line):
            pending_section_roman = True
            continue
        if pending_section_roman and re.match(r"^[A-Za-z]", line):
            section = re.sub(r"\s+", " ", line).strip(" :-")
            pending_section_roman = False
            continue

        sec = _SECTION_INLINE.match(line)
        if sec and ("SECTION" in line.upper() or sec.group("roman")):
            title = re.sub(r"\s+", " ", sec.group("title")).strip(" :-")
            if title and not title.isdigit():
                section = title
                continue

        if pending_num is not None:
            if re.match(r"^[A-Za-z]", line) and not _TOPIC_BARE.match(line):
                title = line.strip()
                if pending_num not in seen and len(title) > 3:
                    seen.add(pending_num)
                    topics.append(
                        SyllabusTopic(
                            number=pending_num,
                            title=title,
                            section=section,
                            subtopics=[],
                        )
                    )
                pending_num = None
                continue
            pending_num = None

        inline = _TOPIC_INLINE.match(line)
        if inline:
            number = int(inline.group("num"))
            title = inline.group("title").strip()
            if 1 <= number <= 20 and number not in seen and len(title) > 3:
                seen.add(number)
                topics.append(
                    SyllabusTopic(number=number, title=title, section=section, subtopics=[])
                )
            continue

        bare = _TOPIC_BARE.match(line)
        if bare:
            pending_num = int(bare.group("num"))
            continue

    return topics


def _parse_subject_content(lines: list[str]) -> list[SyllabusTopic]:
    section: str | None = None
    topics: dict[int, SyllabusTopic] = {}
    current_topic: SyllabusTopic | None = None
    current_sub: SyllabusSubtopic | None = None
    outcome_lines: list[str] = []
    pending_topic_num: int | None = None
    pending_section = False

    def flush_sub() -> None:
        nonlocal current_sub, outcome_lines
        if current_topic is not None and current_sub is not None:
            current_sub.outcomes_text = " ".join(outcome_lines).strip()
            current_topic.subtopics = [
                s for s in current_topic.subtopics if s.code != current_sub.code
            ]
            current_topic.subtopics.append(current_sub)
        current_sub = None
        outcome_lines = []

    for line in lines:
        if not line:
            continue

        if re.match(r"(?i)^SECTION\s+[IVX]+\s*:?\s*$", line):
            pending_section = True
            continue
        if pending_section and re.match(r"^[A-Za-z]", line):
            section = re.sub(r"\s+", " ", line).strip(" :-")
            pending_section = False
            continue

        sec = re.match(r"(?i)^SECTION\s+[IVX]+\s*:\s*(.+)$", line)
        if sec:
            section = re.sub(r"\s+", " ", sec.group(1)).strip(" :-")
            continue

        if pending_topic_num is not None:
            if re.match(r"^[A-Za-z]", line) and line.lower() not in {
                "content",
                "learning outcomes",
                "overview",
            }:
                flush_sub()
                current_topic = SyllabusTopic(
                    number=pending_topic_num,
                    title=line.strip(),
                    section=section,
                    subtopics=[],
                )
                topics[pending_topic_num] = current_topic
                pending_topic_num = None
                continue
            pending_topic_num = None

        inline = _TOPIC_INLINE.match(line)
        if inline:
            number = int(inline.group("num"))
            title = inline.group("title").strip()
            if 1 <= number <= 20 and len(title) > 3:
                flush_sub()
                current_topic = SyllabusTopic(
                    number=number,
                    title=title,
                    section=section,
                    subtopics=[],
                )
                topics[number] = current_topic
                continue

        bare = _TOPIC_BARE.match(line)
        if bare:
            pending_topic_num = int(bare.group("num"))
            continue

        sub_match = _SUBTOPIC_LINE.match(line)
        if sub_match:
            flush_sub()
            code = sub_match.group("code")
            title = sub_match.group("title").strip()
            if current_topic is None:
                major = int(code.split(".", 1)[0])
                current_topic = topics.setdefault(
                    major,
                    SyllabusTopic(number=major, title=f"Topic {major}", section=section),
                )
            current_sub = SyllabusSubtopic(code=code, title=title, outcomes_text="")
            continue

        if current_sub is not None:
            lower = line.lower()
            if lower in {"content", "learning outcomes", "candidates should be able to:"}:
                continue
            outcome_lines.append(line)

    flush_sub()
    return [topics[n] for n in sorted(topics)]
