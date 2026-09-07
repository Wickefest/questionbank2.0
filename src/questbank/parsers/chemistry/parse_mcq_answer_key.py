from __future__ import annotations

import re
from pathlib import Path

from questbank.types.ingest import (
    AnswerKeyEntry,
    AnswerSourceEvidence,
    PaperIdentity,
    normalize_question_ref,
    question_ref_from_number,
)
from questbank.types.layout import BoundingBox
from questbank.types.question import OPTION_LABELS, OptionLabel

# Page-1 MCQ key patterns (Singapore-style mark papers).
_PAIR = re.compile(
    r"(?i)(?:^|[^\d])(?P<num>\d{1,2})\s*[.\)\:\-]?\s*(?P<ans>[ABCD])\b"
)
_STRUCTURED_MARK = re.compile(
    r"(?i)\b(?:paper\s*2|section\s*b|mark\s*scheme|structured)\b"
)

_TOPIC_CHECKLIST = re.compile(
    r"(?i)\b(?:topics?|need to\s*revise|qn\s*number)\b"
)


class AnswerKeyParseResult:
    def __init__(
        self,
        *,
        entries: list[AnswerKeyEntry],
        page_text: str,
        ignored_sections: list[str],
        source_path: str,
    ) -> None:
        self.entries = entries
        self.page_text = page_text
        self.ignored_sections = ignored_sections
        self.source_path = source_path


def parse_mcq_answer_key(
    pdf_path: str | Path,
    *,
    paper_identity: PaperIdentity,
    expected_count: int = 40,
    page_index: int = 0,
) -> AnswerKeyParseResult:
    """Extract Paper 1 MCQ answers from the mark PDF (deterministic).

    Reads consecutive pages that contain Qn/Ans letter pairs (e.g. keys that
    span pages 1-3). Stops before topic checklists or structured mark schemes.
    Does not use an LLM to choose answers.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(
            f"Mark PDF not found: {pdf_path}. "
            "Expected e.g. Chem Mark Paper-45-54.pdf for the pilot ingest."
        )

    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF is required for answer-key extraction") from exc

    ignored: list[str] = []
    page_chunks: list[tuple[int, str, list]] = []
    with pymupdf.open(pdf_path) as doc:
        if doc.page_count < 1:
            raise ValueError(f"Mark PDF has no pages: {pdf_path}")

        cursor = page_index
        while cursor < doc.page_count:
            page = doc[cursor]
            text = page.get_text("text") or ""
            words = page.get_text("words") or []
            page_number = cursor + 1
            # Topic-revision checklists have Q numbers but no A-D answers.
            if _TOPIC_CHECKLIST.search(text) and not _extract_pairs(text):
                ignored.append(f"page_{page_number}:topic_checklist")
                cursor += 1
                # Remaining pages after the MCQ key are ignored.
                for later in range(cursor, doc.page_count):
                    later_text = doc[later].get_text("text") or ""
                    if later_text.strip():
                        ignored.append(f"page_{later + 1}:ignored_after_mcq_key")
                break
            pairs = [
                (n, a, s)
                for n, a, s in _extract_pairs(text)
                if 1 <= n <= expected_count
            ]
            if not pairs:
                if text.strip():
                    label = "structured_mark_scheme" if _STRUCTURED_MARK.search(text) else "no_mcq_pairs"
                    ignored.append(f"page_{page_number}:{label}")
                    for later in range(cursor + 1, doc.page_count):
                        later_text = doc[later].get_text("text") or ""
                        if later_text.strip():
                            ignored.append(f"page_{later + 1}:ignored_after_mcq_key")
                break
            page_chunks.append((page_number, text, words))
            cursor += 1
            if len({n for n, _, _ in pairs}) >= expected_count and cursor > page_index + 1:
                # Rare single-page full key; keep scanning only while useful.
                pass

        # Mark any unread trailing pages as ignored once we stop early.
        if cursor < doc.page_count and not any(
            item.startswith(f"page_{cursor + 1}:") for item in ignored
        ):
            for later in range(cursor, doc.page_count):
                later_text = doc[later].get_text("text") or ""
                if not later_text.strip():
                    continue
                tag = f"page_{later + 1}:"
                if any(i.startswith(tag) for i in ignored):
                    continue
                if _TOPIC_CHECKLIST.search(later_text) and not _extract_pairs(later_text):
                    ignored.append(f"page_{later + 1}:topic_checklist")
                elif _STRUCTURED_MARK.search(later_text):
                    ignored.append(f"page_{later + 1}:structured_mark_scheme")
                else:
                    ignored.append(f"page_{later + 1}:ignored_after_mcq_key")

    if not page_chunks:
        page_text = ""
        entries = []
    else:
        page_text = "\n\n".join(chunk[1] for chunk in page_chunks)
        # Prefer evidence bbox from the page where each number appears.
        by_number: dict[int, AnswerKeyEntry] = {}
        for page_number, text, words in page_chunks:
            for entry in entries_from_page_text(
                text,
                paper_identity=paper_identity,
                origin=str(pdf_path).replace("\\", "/"),
                expected_count=expected_count,
                page_number=page_number,
                words=words,
            ):
                digits = "".join(ch for ch in entry.question_ref if ch.isdigit())
                number = int(digits) if digits else 0
                by_number.setdefault(number, entry)
        entries = [by_number[n] for n in sorted(by_number)]

    return AnswerKeyParseResult(
        entries=entries,
        page_text=page_text,
        ignored_sections=ignored,
        source_path=str(pdf_path).replace("\\", "/"),
    )


def entries_from_page_text(
    page_text: str,
    *,
    paper_identity: PaperIdentity,
    origin: str,
    expected_count: int = 40,
    page_number: int = 1,
    words: list | None = None,
) -> list[AnswerKeyEntry]:
    """Parse Q→A–D pairs from page-1 mark-key text (testable without a PDF)."""
    found = _extract_pairs(page_text)
    by_number: dict[int, tuple[OptionLabel, str]] = {}
    for number, answer, snippet in found:
        if number < 1 or number > expected_count:
            continue
        # First occurrence wins (page 1 key tables sometimes repeat headers).
        by_number.setdefault(number, (answer, snippet))

    entries: list[AnswerKeyEntry] = []
    for number in sorted(by_number):
        answer, snippet = by_number[number]
        bbox = _bbox_for_number(words, number) if words else None
        entries.append(
            AnswerKeyEntry(
                paper_identity=paper_identity,
                question_ref=question_ref_from_number(number),
                correct_option=answer,
                source_evidence=AnswerSourceEvidence(
                    page=page_number,
                    bounding_box=bbox,
                    text_snippet=snippet,
                ),
                origin=origin,
            )
        )
    return entries


def load_answer_key_fixture(
    fixture_path: str | Path,
    *,
    paper_identity: PaperIdentity,
) -> list[AnswerKeyEntry]:
    """Load regression fixture answers (tests / eval only — not runtime parser truth)."""
    import json

    path = Path(fixture_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    answers = payload.get("answers") or payload
    entries: list[AnswerKeyEntry] = []
    if isinstance(answers, dict):
        items = answers.items()
    elif isinstance(answers, list):
        items = [
            (item["question_ref"], item["correct_option"])
            if isinstance(item, dict)
            else item
            for item in answers
        ]
    else:
        raise ValueError(f"Unsupported answer fixture shape in {path}")

    for ref, option in items:
        label = str(option).strip().upper()
        if label not in OPTION_LABELS:
            raise ValueError(f"Invalid option {option!r} for {ref}")
        qref = normalize_question_ref(ref)
        entries.append(
            AnswerKeyEntry(
                paper_identity=paper_identity,
                question_ref=qref,
                correct_option=label,  # type: ignore[arg-type]
                source_evidence=AnswerSourceEvidence(
                    page=0,
                    text_snippet=f"fixture:{qref}={label}",
                ),
                origin=f"fixture:{path.as_posix()}",
            )
        )
    return sorted(entries, key=_question_ref_sort_key)


def _question_ref_sort_key(entry: AnswerKeyEntry) -> tuple[int, str]:
    ref = entry.question_ref
    digits = "".join(ch for ch in ref if ch.isdigit())
    return (int(digits) if digits else 10**9, ref)


def _extract_pairs(page_text: str) -> list[tuple[int, OptionLabel, str]]:
    pairs: list[tuple[int, OptionLabel, str]] = []
    for match in _PAIR.finditer(page_text):
        number = int(match.group("num"))
        answer = match.group("ans").upper()
        if answer not in OPTION_LABELS:
            continue
        snippet = match.group(0).strip()
        pairs.append((number, answer, snippet))  # type: ignore[arg-type]
    return pairs


def _bbox_for_number(words: list, number: int) -> BoundingBox | None:
    """Best-effort word bbox for the printed question number on page 1."""
    target = str(number)
    for word in words:
        # pymupdf words: x0, y0, x1, y1, text, block, line, word
        if len(word) < 5:
            continue
        text = str(word[4]).strip().rstrip(".)")
        if text == target:
            return BoundingBox(x0=float(word[0]), y0=float(word[1]), x1=float(word[2]), y1=float(word[3]))
    return None
