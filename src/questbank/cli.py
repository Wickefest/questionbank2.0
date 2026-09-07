from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from questbank.parsers.chemistry.parse_mcq_paper import parse_chemistry_paper_1
from questbank.parsers.chemistry.parse_structured_paper import (
    format_structured_report,
    parse_structured_paper,
)
from questbank.report import format_parse_report

DEFAULT_PDF = Path("Chem Paper.pdf")
DEFAULT_OUTPUT = Path("output") / "chemistry-paper-1-parsed.json"
DEFAULT_VISUALS = Path("output") / "visuals"
DEFAULT_STRUCTURED_OUTPUT = Path("output") / "ammonia-structured-parsed.json"
DEFAULT_STRUCTURED_VISUALS = Path("output") / "ammonia-visuals"
DEFAULT_ANSWER_PDF = Path("MS1 BBSS - 3E Chemistry (6092) EYE P1 2023 Answers.pdf")


def main(argv: list[str] | None = None) -> int:
    from questbank.config.env import load_questbank_env

    load_questbank_env()
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] in {"ingest-mcq-pilot", "ingest-mcq", "serve"}:
        if args_list[0] == "serve":
            return serve_main(args_list[1:])
        return ingest_main(args_list[1:])
    return _run_legacy_parse(_build_legacy_parser().parse_args(args_list))


def ingest_main(argv: list[str] | None = None) -> int:
    """Console entry for MCQ ingest (Docling + Gemini)."""
    from questbank.config.env import load_questbank_env

    load_questbank_env()
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] in {"ingest-mcq-pilot", "ingest-mcq"}:
        args_list = args_list[1:]
    return _run_ingest(_build_ingest_parser().parse_args(args_list))


def serve_main(argv: list[str] | None = None) -> int:
    from questbank.config.env import load_questbank_env

    load_questbank_env()
    parser = argparse.ArgumentParser(description="Serve FastAPI MCQ ingest API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    import uvicorn

    uvicorn.run("questbank.api.app:app", host=args.host, port=args.port, reload=False)
    return 0


def _build_legacy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse Chemistry exam PDFs (heuristic Docling layout or structured)."
    )
    parser.add_argument(
        "pdf",
        nargs="?",
        default=str(DEFAULT_PDF),
        help="Path to the Chemistry PDF (default: Chem Paper.pdf)",
    )
    parser.add_argument(
        "--mode",
        choices=("mcq", "structured"),
        default="mcq",
        help="Parse mode (default: mcq)",
    )
    parser.add_argument(
        "--engine",
        choices=("docling",),
        default="docling",
        help="Heuristic layout engine only (Gemini ingest: use parse-chemistry-ingest)",
    )
    parser.add_argument("-o", "--output", default=None, help="Path for debug JSON")
    parser.add_argument(
        "--backend",
        choices=("auto", "docling", "pymupdf"),
        default="auto",
        help="Layout backend (default: auto)",
    )
    parser.add_argument(
        "--ocr",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Force Docling OCR on/off",
    )
    parser.add_argument("--vision-dpi", type=int, default=180)
    parser.add_argument(
        "--extract-visuals",
        action="store_true",
        help="Crop diagram/graph/apparatus images and attach paths",
    )
    parser.add_argument("--visuals-dir", default=None)
    parser.add_argument(
        "--expected-count",
        type=int,
        default=None,
        help="Expected MCQ count for validation metadata (optional)",
    )
    return parser


def _build_ingest_parser() -> argparse.ArgumentParser:
    ingest = argparse.ArgumentParser(
        prog="parse-chemistry-ingest",
        description=(
            "MCQ ingest: Docling + Gemini questions/answers, deterministic match, "
            "validation, optional Supabase DRAFT push under output/<run-id>/"
        ),
    )
    ingest.add_argument(
        "--question-pdf",
        default=str(DEFAULT_PDF),
        help="Question paper PDF",
    )
    ingest.add_argument(
        "--answer-pdf",
        "--mark-pdf",
        dest="answer_pdf",
        default=None,
        help="Answer key / mark scheme PDF (required)",
    )
    ingest.add_argument("--output-root", default="output")
    ingest.add_argument("--run-id", default=None)
    ingest.add_argument("--title", default=None)
    ingest.add_argument("--subject", default="Chemistry")
    ingest.add_argument("--exam-year", type=int, default=2023)
    ingest.add_argument("--paper-code", default="6092/01")
    ingest.add_argument(
        "--expected-count",
        type=int,
        default=None,
        help="Optional expected question count for validation (not hardcoded in parser)",
    )
    ingest.add_argument(
        "--backend",
        choices=("auto", "docling", "pymupdf"),
        default="auto",
        help="Layout backend (default: auto / Docling)",
    )
    ingest.add_argument("--dpi", type=int, default=150)
    ingest.add_argument("--ocr", action=argparse.BooleanOptionalAction, default=None)
    ingest.add_argument(
        "--push-supabase",
        action="store_true",
        help="After parsing/validation, upsert DRAFT/NEEDS_REVIEW records to Supabase",
    )
    ingest.add_argument(
        "--allow-partial-match",
        action="store_true",
        help="Do not fail the matching stage when coverage is incomplete",
    )
    return ingest


def _run_ingest(args: argparse.Namespace) -> int:
    from questbank.ingest.runner import run_mcq_ingest
    from questbank.types.ingest import PaperIdentity

    question_pdf = Path(args.question_pdf)
    if not question_pdf.exists():
        print(f"Question PDF not found: {question_pdf}", file=sys.stderr)
        return 2

    answer_pdf = Path(args.answer_pdf) if args.answer_pdf else None
    if answer_pdf is None or not answer_pdf.exists():
        # Try common BBSS mark scheme next to the question PDF
        candidate = question_pdf.parent / DEFAULT_ANSWER_PDF.name
        if candidate.exists():
            answer_pdf = candidate
        else:
            print(
                "Answer PDF required (--answer-pdf). Syllabus PDF is not used.",
                file=sys.stderr,
            )
            return 2

    identity = PaperIdentity(
        source_exam_year=args.exam_year,
        paper_code=args.paper_code,
        paper_type="mcq",
    )
    manifest = run_mcq_ingest(
        question_pdf=question_pdf,
        answer_pdf=answer_pdf,
        output_root=args.output_root,
        run_id=args.run_id,
        paper_identity=identity,
        expected_question_count=args.expected_count,
        title=args.title,
        subject=args.subject,
        backend=args.backend,
        ocr=args.ocr,
        dpi=args.dpi,
        push_supabase=args.push_supabase,
        require_full_answer_match=not args.allow_partial_match,
    )
    print(json.dumps(manifest.model_dump(by_alias=True), indent=2))
    failed = [s for s in manifest.stages if s.status == "failed"]
    return 1 if failed else 0


def _run_legacy_parse(args: argparse.Namespace) -> int:
    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"PDF not found: {pdf}", file=sys.stderr)
        return 2

    if args.mode == "structured":
        visuals_dir = Path(args.visuals_dir) if args.visuals_dir else DEFAULT_STRUCTURED_VISUALS
        paper = parse_structured_paper(
            pdf,
            backend=args.backend,
            ocr=args.ocr,
            extract_visuals=args.extract_visuals,
            visuals_dir=visuals_dir if args.extract_visuals else None,
        )
        out = Path(args.output) if args.output else DEFAULT_STRUCTURED_OUTPUT
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(paper.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
        print(format_structured_report(paper))
        print(f"Wrote {out}")
        return 0 if paper.validation.status == "pass" else 1

    expected = args.expected_count if args.expected_count is not None else 40
    visuals_dir = Path(args.visuals_dir) if args.visuals_dir else DEFAULT_VISUALS
    paper = parse_chemistry_paper_1(
        pdf,
        backend=args.backend,
        ocr=args.ocr,
        expected_count=expected,
        extract_visuals=args.extract_visuals,
        visuals_dir=visuals_dir if args.extract_visuals else None,
    )
    out = Path(args.output) if args.output else DEFAULT_OUTPUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(paper.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
    print(format_parse_report(paper))
    print(f"Wrote {out}")
    return 0 if paper.validation.review_count == 0 else 1
