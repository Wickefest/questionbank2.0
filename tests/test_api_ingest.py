"""FastAPI ingest endpoint smoke tests (mocked Gemini)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from questbank.types.ingest import DocumentManifest, PaperIdentity, StageResult


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import questbank.api.app as app_mod

    def fake_ingest(**kwargs):
        out = Path(kwargs["output_root"]) / (kwargs.get("run_id") or "test-run")
        out.mkdir(parents=True, exist_ok=True)
        (out / "questions.json").write_text("{}", encoding="utf-8")
        (out / "answers.json").write_text("{}", encoding="utf-8")
        (out / "matched_questions.json").write_text("{}", encoding="utf-8")
        (out / "validation_report.json").write_text("{}", encoding="utf-8")
        (out / "assets").mkdir(exist_ok=True)
        return DocumentManifest(
            run_id=kwargs.get("run_id") or "test-run",
            paper_identity=PaperIdentity(source_exam_year=2023, paper_code="6092/01", paper_type="mcq"),
            expected_question_count=kwargs.get("expected_question_count") or 0,
            stages=[
                StageResult(name="parse_questions", status="succeeded", message="ok"),
                StageResult(name="parse_answers", status="succeeded", message="ok"),
                StageResult(name="matching", status="succeeded", message="ok"),
                StageResult(name="validation", status="succeeded", message="ok"),
            ],
        )

    monkeypatch.setattr(app_mod, "run_mcq_ingest", fake_ingest)
    return TestClient(app_mod.app)


def test_health(client: TestClient):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_ingest_mcq_upload(client: TestClient, tmp_path: Path):
    q = tmp_path / "q.pdf"
    a = tmp_path / "a.pdf"
    q.write_bytes(b"%PDF-1.4")
    a.write_bytes(b"%PDF-1.4")
    res = client.post(
        "/ingest/mcq",
        files={
            "question_pdf": ("q.pdf", q.read_bytes(), "application/pdf"),
            "answer_pdf": ("a.pdf", a.read_bytes(), "application/pdf"),
        },
        data={
            "year": "2023",
            "paper_code": "6092/01",
            "expected_question_count": "40",
            "output_root": str(tmp_path / "out"),
            "run_id": "api-test",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["run_id"] == "api-test"
    assert "artifacts" in body


def test_ingest_rejects_non_pdf(client: TestClient):
    res = client.post(
        "/ingest/mcq",
        files={
            "question_pdf": ("q.txt", b"nope", "text/plain"),
            "answer_pdf": ("a.pdf", b"%PDF", "application/pdf"),
        },
    )
    assert res.status_code == 400
