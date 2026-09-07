"""FastAPI upload surface for Chemistry MCQ ingest."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from questbank.config.env import load_questbank_env
from questbank.ingest.runner import run_mcq_ingest
from questbank.types.ingest import PaperIdentity

load_questbank_env()

app = FastAPI(
    title="EduNets Chemistry MCQ Ingest",
    description="Upload question + answer PDFs; parse with Docling + Gemini; store drafts.",
    version="0.2.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest/mcq")
async def ingest_mcq(
    question_pdf: UploadFile = File(..., description="Question paper PDF"),
    answer_pdf: UploadFile = File(..., description="Answer key / mark scheme PDF"),
    title: str | None = Form(default=None),
    subject: str = Form(default="Chemistry"),
    year: int | None = Form(default=None),
    paper_code: str = Form(default="6092/01"),
    expected_question_count: int | None = Form(default=None),
    push_supabase: bool = Form(default=False),
    output_root: str = Form(default="output"),
    run_id: str | None = Form(default=None),
) -> dict[str, Any]:
    """Accept question + answer PDFs; do not require a syllabus PDF."""
    if not question_pdf.filename or not question_pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="question_pdf must be a PDF")
    if not answer_pdf.filename or not answer_pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="answer_pdf must be a PDF")

    identity = PaperIdentity(
        source_exam_year=year or 0,
        paper_code=paper_code,
        paper_type="mcq",
    )

    with tempfile.TemporaryDirectory(prefix="questbank-ingest-") as tmp:
        tmp_path = Path(tmp)
        q_path = tmp_path / "question.pdf"
        a_path = tmp_path / "answer.pdf"
        q_path.write_bytes(await question_pdf.read())
        a_path.write_bytes(await answer_pdf.read())

        try:
            manifest = run_mcq_ingest(
                question_pdf=q_path,
                answer_pdf=a_path,
                output_root=output_root,
                run_id=run_id,
                paper_identity=identity,
                expected_question_count=expected_question_count,
                title=title or question_pdf.filename,
                subject=subject,
                push_supabase=push_supabase,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    out_dir = Path(output_root) / manifest.run_id
    failed = [s for s in manifest.stages if s.status == "failed"]
    return {
        "run_id": manifest.run_id,
        "ok": len(failed) == 0,
        "output_dir": str(out_dir).replace("\\", "/"),
        "stages": [s.model_dump(by_alias=True) for s in manifest.stages],
        "expected_question_count": expected_question_count,
        "artifacts": {
            "questions": str(out_dir / "questions.json").replace("\\", "/"),
            "answers": str(out_dir / "answers.json").replace("\\", "/"),
            "matched_questions": str(out_dir / "matched_questions.json").replace("\\", "/"),
            "validation_report": str(out_dir / "validation_report.json").replace("\\", "/"),
            "assets": str(out_dir / "assets").replace("\\", "/"),
        },
    }


def serve() -> None:
    """Console entry: ``questbank-serve``."""
    import uvicorn

    load_questbank_env()
    uvicorn.run("questbank.api.app:app", host="0.0.0.0", port=8000, reload=False)


__all__ = ["app", "serve"]
