from __future__ import annotations

import argparse
import json
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse Chemistry exam PDFs (MCQ Paper 1 or structured written papers)."
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
        choices=("docling", "vision"),
        default="docling",
        help=(
            "Structured parse engine: docling+OCR (default) or Gemini vision for scanned pages. "
            "Vision requires GEMINI_API_KEY."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Path for debug JSON",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "docling", "pymupdf"),
        default="auto",
        help="Layout backend for docling engine (default: auto)",
    )
    parser.add_argument(
        "--ocr",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Force Docling OCR on/off (default: auto for sparse/scanned PDFs; structured defaults on)",
    )
    parser.add_argument(
        "--vision-dpi",
        type=int,
        default=180,
        help="Render DPI for --engine vision (default: 180)",
    )
    parser.add_argument(
        "--extract-visuals",
        action="store_true",
        help="Crop diagram/graph/apparatus images and attach paths",
    )
    parser.add_argument(
        "--visuals-dir",
        default=None,
        help="Directory for cropped visuals",
    )
    args = parser.parse_args(argv)

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    if args.mode == "structured":
        output_path = Path(args.output) if args.output else DEFAULT_STRUCTURED_OUTPUT
        visuals_dir = Path(args.visuals_dir) if args.visuals_dir else DEFAULT_STRUCTURED_VISUALS
        if args.engine == "vision":
            from questbank.parsers.chemistry.parse_structured_vision import (
                parse_structured_paper_vision,
            )

            paper = parse_structured_paper_vision(
                pdf_path,
                dpi=args.vision_dpi,
                extract_visuals=True,
                visuals_dir=visuals_dir,
            )
        else:
            ocr = True if args.ocr is None else args.ocr
            paper = parse_structured_paper(
                pdf_path,
                backend=args.backend,
                ocr=ocr,
                extract_visuals=args.extract_visuals,
                visuals_dir=visuals_dir,
            )
        report = format_structured_report(paper)
        payload = paper.model_dump(by_alias=True, exclude_none=False)
    else:
        if args.engine == "vision":
            raise SystemExit("--engine vision is only supported with --mode structured")
        output_path = Path(args.output) if args.output else DEFAULT_OUTPUT
        visuals_dir = Path(args.visuals_dir) if args.visuals_dir else DEFAULT_VISUALS
        paper = parse_chemistry_paper_1(
            pdf_path,
            backend=args.backend,
            extract_visuals=args.extract_visuals,
            visuals_dir=visuals_dir,
            ocr=args.ocr,
        )
        report = format_parse_report(paper)
        payload = paper.model_dump(by_alias=True, exclude_none=False)

    print(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote debug JSON: {output_path}")
    if args.extract_visuals or (args.mode == "structured" and args.engine == "vision"):
        print(f"Visual crops directory: {visuals_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
