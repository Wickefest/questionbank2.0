"""Canonical MCQ ingest: matching, validation, join — no Qwen."""

from __future__ import annotations

from pathlib import Path

import pytest

from questbank.ingest.runner import (
    join_into_complete_records,
    match_questions_and_answers,
    run_mcq_ingest,
)
from questbank.parsers.chemistry.parse_mcq_answer_key import (
    entries_from_page_text,
    load_answer_key_fixture,
)
from questbank.types.canonical import (
    CompleteQuestionRecord,
    CompositeVisualOptions,
    ImageBlock,
    ParsedAnswer,
    ParsedQuestion,
    TextBlock,
    TextOptionItem,
    TextOptions,
)
from questbank.types.ingest import PaperIdentity
from questbank.validation.validate_canonical import validate_canonical_ingest

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "chem_paper1_2023_answer_key.json"
IDENTITY = PaperIdentity(source_exam_year=2023, paper_code="6092/01", paper_type="mcq")

PAGE1_KEY_TEXT = """
CHEMISTRY 6092/01 Answers
1 B  2 A  3 C  4 D  5 D  6 D  7 A  8 B  9 A  10 C
11 C  12 A  13 A  14 A  15 D  16 A  17 B  18 D  19 A  20 C
21 C  22 B  23 B  24 D  25 D  26 A  27 D  28 A  29 D  30 C
31 B  32 B  33 D  34 A  35 B  36 C  37 D  38 D  39 B  40 C
"""


def test_answer_key_page_text_extracts_forty():
    entries = entries_from_page_text(
        PAGE1_KEY_TEXT,
        paper_identity=IDENTITY,
        origin="mock://page1",
        expected_count=40,
    )
    assert len(entries) == 40
    by_ref = {e.question_ref: e.correct_option for e in entries}
    assert by_ref["Q1"] == "B"
    assert by_ref["Q4"] == "D"
    assert by_ref["Q40"] == "C"


def test_fixture_matches_supplied_regression_key():
    entries = load_answer_key_fixture(FIXTURE, paper_identity=IDENTITY)
    assert len(entries) == 40
    by_ref = {e.question_ref: e.correct_option for e in entries}
    assert [by_ref[f"Q{i}"] for i in range(1, 11)] == list("BACDDDABAC")


def test_matching_by_normalized_ref():
    questions = [_text_question(str(n)) for n in range(1, 41)]
    answers = [
        ParsedAnswer(question_ref=str(n), answer=e.correct_option, explanation=None)
        for n, e in enumerate(load_answer_key_fixture(FIXTURE, paper_identity=IDENTITY), start=1)
    ]
    # Also accept zero-padded refs
    answers[3] = ParsedAnswer(question_ref="04", answer="D", explanation=None)
    report = match_questions_and_answers(questions, answers)
    assert len(report.matched) == 40
    assert report.unmatched_questions == []
    assert report.unused_answers == []


def test_join_preserves_mark_scheme_explanation_only():
    questions = [_text_question("4")]
    answers = [
        ParsedAnswer(question_ref="4", answer="D", explanation="Official mark scheme note."),
    ]
    matching = match_questions_and_answers(questions, answers)
    records = join_into_complete_records(questions, answers, matching)
    assert records[0].answer is not None
    assert records[0].answer.value == "D"
    assert records[0].answer.explanation == "Official mark scheme note."
    assert records[0].answer.explanation_source == "mark_scheme"
    assert records[0].classification is None


def test_join_null_explanation_when_absent():
    questions = [_text_question("1")]
    answers = [ParsedAnswer(question_ref="1", answer="B", explanation=None)]
    matching = match_questions_and_answers(questions, answers)
    records = join_into_complete_records(questions, answers, matching)
    assert records[0].answer is not None
    assert records[0].answer.explanation is None
    assert records[0].answer.explanation_source is None


def test_join_does_not_invent_answers_for_unmatched():
    questions = [_text_question(str(n)) for n in range(1, 5)]
    answers = [ParsedAnswer(question_ref="1", answer="B")]
    matching = match_questions_and_answers(questions, answers)
    records = join_into_complete_records(questions, answers, matching)
    by_ref = {r.question_ref: r for r in records}
    assert by_ref["1"].answer is not None
    assert by_ref["2"].answer is None
    assert by_ref["2"].status == "NEEDS_REVIEW"


def test_validation_composite_requires_asset(tmp_path: Path):
    q = ParsedQuestion(
        question_ref="4",
        content=[TextBlock(value="Which arrangement?")],
        options=CompositeVisualOptions(labels=["A", "B", "C", "D"], asset="q04-options.png"),
    )
    answers = [ParsedAnswer(question_ref="4", answer="D")]
    matching = match_questions_and_answers([q], answers)
    records = join_into_complete_records([q], answers, matching)
    report = validate_canonical_ingest(
        questions=[q],
        answers=answers,
        records=records,
        matching=matching,
        assets_dir=tmp_path,
        expected_question_count=1,
    )
    assert any(i.code == "MISSING_ASSET_FILE" for i in report.issues)

    (tmp_path / "q04-options.png").write_bytes(b"png")
    report2 = validate_canonical_ingest(
        questions=[q],
        answers=answers,
        records=records,
        matching=matching,
        assets_dir=tmp_path,
        expected_question_count=1,
    )
    assert not any(i.code == "MISSING_ASSET_FILE" for i in report2.issues)


def test_plain_text_question_has_no_image_block():
    q = _text_question("11")
    assert not any(getattr(b, "type", None) == "image" for b in q.content)


def test_ingest_runner_mocked_gemini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from questbank.ingest import runner as runner_mod
    from questbank.llm.gemini_client import GeminiClient

    questions = [_text_question(str(n)) for n in range(1, 41)]
    answers = [
        ParsedAnswer(question_ref=str(n), answer=e.correct_option)
        for n, e in enumerate(load_answer_key_fixture(FIXTURE, paper_identity=IDENTITY), start=1)
    ]

    monkeypatch.setattr(
        runner_mod,
        "parse_mcq_questions_gemini",
        lambda *a, **k: questions,
    )
    monkeypatch.setattr(
        runner_mod,
        "parse_mcq_answers_gemini",
        lambda *a, **k: answers,
    )
    monkeypatch.setattr(runner_mod, "_page_count", lambda _p: 1)
    monkeypatch.setattr(runner_mod, "_file_sha256", lambda _p: "abc")

    class FakeClient(GeminiClient):
        def ensure_available(self) -> None:
            return None

    q_pdf = tmp_path / "q.pdf"
    a_pdf = tmp_path / "a.pdf"
    q_pdf.write_bytes(b"%PDF-1.4 fake")
    a_pdf.write_bytes(b"%PDF-1.4 fake")

    manifest = run_mcq_ingest(
        question_pdf=q_pdf,
        answer_pdf=a_pdf,
        output_root=tmp_path / "out",
        run_id="unit-canonical",
        paper_identity=IDENTITY,
        expected_question_count=40,
        client=FakeClient(api_key="x", model="gemini-2.5-flash"),
        check_gemini=False,
        push_supabase=False,
    )

    out = tmp_path / "out" / "unit-canonical"
    assert (out / "questions.json").exists()
    assert (out / "answers.json").exists()
    assert (out / "matched_questions.json").exists()
    assert (out / "validation_report.json").exists()
    assert (out / "document_manifest.json").exists()
    assert any(s.name == "matching" and s.status == "succeeded" for s in manifest.stages)


def _text_question(ref: str) -> ParsedQuestion:
    return ParsedQuestion(
        question_ref=ref,
        content=[TextBlock(value=f"Stem for question {ref}?")],
        options=TextOptions(
            items=[
                TextOptionItem(label="A", content="option A"),
                TextOptionItem(label="B", content="option B"),
                TextOptionItem(label="C", content="option C"),
                TextOptionItem(label="D", content="option D"),
            ]
        ),
        source_page=1,
        requires_review=False,
    )
