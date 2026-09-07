from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

from questbank.syllabus.parse_syllabus_pdf import SyllabusTaxonomy
from questbank.types.ingest import PaperIdentity, QuestionRecord
from questbank.types.question import OPTION_LABELS

logger = logging.getLogger(__name__)


def get_supabase_client() -> Any | None:
    """Return a Supabase client when URL+key are configured; else None.

    Missing credentials skip upload (experiment still writes local crops).
    Does not invent mock storage results.
    """
    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (os.environ.get("SUPABASE_KEY") or "").strip()
    if not url or not key:
        return None
    if "your-project" in url or key.startswith("your-"):
        logger.warning("Supabase env still has placeholders; upload disabled")
        return None
    try:
        from supabase import create_client
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "supabase package is required for uploads. "
            "Install with: pip install 'questbank[supabase]'"
        ) from exc
    return create_client(url, key)


def questions_bucket() -> str:
    return (os.environ.get("SUPABASE_QUESTIONS_BUCKET") or "questions").strip() or "questions"


def upload_question_png(
    client: Any,
    *,
    storage_path: str,
    png_bytes: bytes,
    bucket: str | None = None,
) -> str:
    """Upload PNG bytes; return public URL. Raises on failure (no silent mock)."""
    bucket_name = bucket or questions_bucket()
    client.storage.from_(bucket_name).upload(
        path=storage_path,
        file=png_bytes,
        file_options={"content-type": "image/png", "upsert": "true"},
    )
    return client.storage.from_(bucket_name).get_public_url(storage_path)


def push_mcq_bank(
    *,
    records: list[QuestionRecord],
    paper_identity: PaperIdentity,
    bank_name: str,
    source_files: list[str],
    taxonomy: SyllabusTaxonomy | None = None,
    client: Any | None = None,
    upload_media: bool = True,
) -> dict[str, Any]:
    """Replace-by-bank upsert into question_banks / questions / options / media.

    Requires a configured Supabase client (service role recommended).
    """
    sb = client if client is not None else get_supabase_client()
    if sb is None:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_KEY "
            "(non-placeholder) to push."
        )

    bank_id = _ensure_bank(
        sb,
        bank_name=bank_name,
        source_files=source_files,
        taxonomy=taxonomy,
    )
    _replace_bank_questions(sb, bank_id)

    if upload_media:
        _ensure_questions_bucket(sb)

    option_rows = 0
    media_rows = 0
    media_warnings: list[str] = []
    for record in records:
        question_id = str(uuid.uuid4())
        question_row = map_question_row(record, bank_id=bank_id, question_id=question_id)
        _insert(sb, "questions", question_row)

        options = map_option_rows(record, question_id=question_id)
        if options:
            _insert(sb, "question_options", options)
            option_rows += len(options)

        if upload_media:
            try:
                media = _upload_and_map_media(sb, record, question_id=question_id)
            except Exception as exc:  # noqa: BLE001
                media_warnings.append(f"{record.question_ref}: {exc}")
                media = []
            if media:
                _insert(sb, "question_media", media)
                media_rows += len(media)

    return {
        "bank_id": bank_id,
        "bank_name": bank_name,
        "questions": len(records),
        "options": option_rows,
        "media": media_rows,
        "media_warnings": media_warnings,
    }


def _ensure_questions_bucket(client: Any) -> None:
    """Create the questions storage bucket when missing (best-effort)."""
    bucket = questions_bucket()
    try:
        existing = client.storage.list_buckets()
        names = {getattr(item, "name", None) or item.get("name") for item in (existing or [])}
        if bucket in names:
            return
        client.storage.create_bucket(bucket, options={"public": True})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not ensure storage bucket %s: %s", bucket, exc)


def map_question_row(
    record: QuestionRecord,
    *,
    bank_id: str,
    question_id: str | None = None,
) -> dict[str, Any]:
    question = record.question
    topic = record.topic_classification
    warnings = [issue.message for issue in question.validation.issues]
    if record.correct_option is None:
        warnings.append("No matched correct_option from answer key")
    status = "parsed"
    if topic and topic.status == "needs_review":
        status = "needs_review"
    if question.validation.status == "review":
        status = "needs_review"

    source = {
        "paperIdentity": record.paper_identity.model_dump(by_alias=True),
        "sourceKey": record.source_key,
        "questionRef": record.question_ref,
        "sourceRegions": [r.model_dump(by_alias=True) for r in record.source_regions],
        "content": [b.model_dump(by_alias=True) for b in question.content],
        "tables": [t.model_dump(by_alias=True) for t in question.tables],
        "visual": question.visual.model_dump(by_alias=True),
    }
    answer_source = None
    if record.answer_source is not None:
        answer_source = record.answer_source.model_dump(by_alias=True)

    return {
        "id": question_id or str(uuid.uuid4()),
        "bank_id": bank_id,
        "number": str(question.question_number),
        "stem": question.stem,
        "marks": 1,
        "correct_answer": record.correct_option,
        "question_type": "mcq",
        "bloom_level": "unspecified",
        "difficulty": "unspecified",
        "type_confidence": 0.0,
        "bloom_confidence": 0.0,
        "tags": [],
        "topic": topic.topic if topic else None,
        "parent_topic": topic.parent_topic if topic else None,
        "subject": (topic.subject if topic else "Chemistry"),
        "syllabus_code": topic.syllabus_code if topic else paper_syllabus_code(record.paper_identity),
        "topic_confidence": topic.topic_confidence if topic else None,
        "topic_match_reasoning": topic.topic_match_reasoning if topic else None,
        "topic_match_method": topic.topic_match_method if topic else None,
        "status": status,
        "parse_warnings": warnings,
        "source": source,
        "answer_source": answer_source,
        "parts": None,
        "keep_together": False,
        "set_context": None,
    }


def map_option_rows(record: QuestionRecord, *, question_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, label in enumerate(OPTION_LABELS):
        option = record.question.options.get(label)
        if option is None:
            continue
        text = option.text
        if text is None or not str(text).strip():
            text = "[visual option]" if option.requires_visual else ""
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "question_id": question_id,
                "label": label,
                "text": text,
                "is_correct": record.correct_option == label if record.correct_option else False,
                "sort_order": index,
                "media": None,
            }
        )
    return rows


def map_media_row(
    *,
    question_id: str,
    storage_path: str,
    public_url: str,
    page_number: int | None,
    image_index: int,
    width: int | None,
    height: int | None,
    bbox: list[float] | None,
    role: str | None,
    option_label: str | None,
    caption: str | None = None,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "question_id": question_id,
        "storage_path": storage_path,
        "public_url": public_url,
        "page_number": page_number,
        "image_index": image_index,
        "width": width,
        "height": height,
        "bbox": bbox,
        "caption": caption,
        "description": None,
        "role": role,
        "option_label": option_label,
    }


def paper_syllabus_code(identity: PaperIdentity) -> str:
    code = identity.paper_code.split("/", 1)[0].strip() or "6092"
    return code


def _ensure_bank(
    client: Any,
    *,
    bank_name: str,
    source_files: list[str],
    taxonomy: SyllabusTaxonomy | None,
) -> str:
    syllabus_payload = taxonomy.model_dump(by_alias=True) if taxonomy is not None else None
    existing = (
        client.table("question_banks")
        .select("id")
        .eq("name", bank_name)
        .limit(1)
        .execute()
    )
    rows = getattr(existing, "data", None) or []
    if rows:
        bank_id = rows[0]["id"]
        client.table("question_banks").update(
            {
                "source_files": source_files,
                "syllabus": syllabus_payload,
            }
        ).eq("id", bank_id).execute()
        return bank_id

    bank_id = str(uuid.uuid4())
    client.table("question_banks").insert(
        {
            "id": bank_id,
            "name": bank_name,
            "source_files": source_files,
            "syllabus": syllabus_payload,
        }
    ).execute()
    return bank_id


def _replace_bank_questions(client: Any, bank_id: str) -> None:
    existing = (
        client.table("questions")
        .select("id")
        .eq("bank_id", bank_id)
        .execute()
    )
    rows = getattr(existing, "data", None) or []
    ids = [row["id"] for row in rows if row.get("id")]
    if not ids:
        return
    # Delete children first, then questions.
    client.table("question_media").delete().in_("question_id", ids).execute()
    client.table("question_options").delete().in_("question_id", ids).execute()
    client.table("questions").delete().eq("bank_id", bank_id).execute()


def _upload_and_map_media(
    client: Any,
    record: QuestionRecord,
    *,
    question_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, asset in enumerate(record.question.visual.assets):
        path = Path(asset.path) if asset.path else None
        if path is None or not path.exists():
            logger.warning("Skipping missing asset for %s: %s", record.question_ref, asset.path)
            continue
        png_bytes = path.read_bytes()
        storage_path = (
            f"exam_questions/{record.source_key.replace('|', '_')}/"
            f"{path.name}"
        )
        public_url = upload_question_png(
            client,
            storage_path=storage_path,
            png_bytes=png_bytes,
        )
        box = asset.bounding_box
        bbox = [box.x0, box.y0, box.x1, box.y1] if box else None
        width = height = None
        try:
            from PIL import Image
            from io import BytesIO

            with Image.open(BytesIO(png_bytes)) as img:
                width, height = img.size
        except Exception:  # noqa: BLE001
            pass
        rows.append(
            map_media_row(
                question_id=question_id,
                storage_path=storage_path,
                public_url=public_url,
                page_number=asset.page,
                image_index=index,
                width=width,
                height=height,
                bbox=bbox,
                role=asset.role,
                option_label=asset.option_label,
            )
        )
    return rows


def _insert(client: Any, table: str, rows: dict[str, Any] | list[dict[str, Any]]) -> None:
    client.table(table).insert(rows).execute()


def push_canonical_bank(
    *,
    records: list[Any],
    paper_identity: PaperIdentity,
    bank_name: str,
    source_files: list[str],
    assets_dir: str | Path,
    client: Any | None = None,
    upload_media: bool = True,
) -> dict[str, Any]:
    """Persist canonical CompleteQuestionRecord drafts to Supabase."""
    from questbank.types.canonical import (
        CompleteQuestionRecord,
        CompositeVisualOptions,
        ImageBlock,
        MathOptions,
        MixedOptions,
        TableOptions,
        TextOptions,
    )
    from questbank.validation.validate_canonical import option_labels

    sb = client if client is not None else get_supabase_client()
    if sb is None:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_KEY "
            "(non-placeholder) to push."
        )

    assets_path = Path(assets_dir)
    bank_id = _ensure_bank(
        sb,
        bank_name=bank_name,
        source_files=source_files,
        taxonomy=None,
    )
    _replace_bank_questions(sb, bank_id)
    if upload_media:
        _ensure_questions_bucket(sb)

    option_rows = 0
    media_rows = 0
    media_warnings: list[str] = []

    for record in records:
        if not isinstance(record, CompleteQuestionRecord):
            record = CompleteQuestionRecord.model_validate(record)
        question_id = str(uuid.uuid4())
        status = record.status if record.status in {"DRAFT", "NEEDS_REVIEW", "APPROVED", "PUBLISHED"} else "DRAFT"
        if record.requires_review:
            status = "NEEDS_REVIEW"

        stem_parts = []
        for block in record.content:
            if getattr(block, "type", None) == "text":
                stem_parts.append(getattr(block, "value", "") or "")
            elif getattr(block, "type", None) == "chemistry":
                stem_parts.append(getattr(block, "value", "") or "")
            elif getattr(block, "type", None) == "math":
                stem_parts.append(getattr(block, "latex", "") or "")
        stem = " ".join(p for p in stem_parts if p).strip() or f"Question {record.question_ref}"

        source = {
            "paperIdentity": paper_identity.model_dump(by_alias=True),
            "questionRef": record.question_ref,
            "content": [b.model_dump() for b in record.content],
            "options": record.options.model_dump(),
            "sourcePage": record.source_page,
            "sourceRegions": [r.model_dump() for r in record.source_regions],
            "classification": None,
        }
        answer_source = None
        if record.answer is not None:
            answer_source = {
                "value": record.answer.value,
                "explanation": record.answer.explanation,
                "explanation_source": record.answer.explanation_source,
            }

        question_row = {
            "id": question_id,
            "bank_id": bank_id,
            "number": str(record.question_ref),
            "stem": stem,
            "marks": 1,
            "correct_answer": record.answer.value if record.answer else None,
            "question_type": "mcq",
            "bloom_level": "unspecified",
            "difficulty": "unspecified",
            "type_confidence": 0.0,
            "bloom_confidence": 0.0,
            "tags": [],
            "topic": None,
            "parent_topic": None,
            "subject": "Chemistry",
            "syllabus_code": paper_syllabus_code(paper_identity),
            "topic_confidence": None,
            "topic_match_reasoning": None,
            "topic_match_method": None,
            "status": status,
            "parse_warnings": [],
            "source": source,
            "answer_source": answer_source,
            "parts": None,
            "keep_together": False,
            "set_context": None,
        }
        _insert(sb, "questions", question_row)

        # Options table rows for text-like modes
        labels = option_labels(record.options)
        for index, label in enumerate(labels):
            text = ""
            opts = record.options
            if isinstance(opts, TextOptions):
                item = next((i for i in opts.items if i.label == label), None)
                text = item.content if item else ""
            elif isinstance(opts, MathOptions):
                item = next((i for i in opts.items if i.label == label), None)
                text = item.latex if item else ""
            elif isinstance(opts, TableOptions):
                row = next((r for r in opts.rows if r.label == label), None)
                text = " | ".join(row.cells) if row else ""
            elif isinstance(opts, CompositeVisualOptions):
                text = "[composite visual]"
            elif isinstance(opts, MixedOptions):
                item = next((i for i in opts.items if i.label == label), None)
                text = (item.content or item.latex or "[mixed]") if item else ""
            _insert(
                sb,
                "question_options",
                {
                    "id": str(uuid.uuid4()),
                    "question_id": question_id,
                    "label": label,
                    "text": text,
                    "is_correct": bool(record.answer and record.answer.value == label),
                    "sort_order": index,
                    "media": None,
                },
            )
            option_rows += 1

        if upload_media:
            try:
                media = _upload_canonical_media(
                    sb,
                    record,
                    question_id=question_id,
                    assets_dir=assets_path,
                    paper_identity=paper_identity,
                )
                if media:
                    _insert(sb, "question_media", media)
                    media_rows += len(media)
            except Exception as exc:  # noqa: BLE001
                media_warnings.append(f"{record.question_ref}: {exc}")

    return {
        "bank_id": bank_id,
        "bank_name": bank_name,
        "questions": len(records),
        "options": option_rows,
        "media": media_rows,
        "media_warnings": media_warnings,
    }


def _upload_canonical_media(
    client: Any,
    record: Any,
    *,
    question_id: str,
    assets_dir: Path,
    paper_identity: PaperIdentity,
) -> list[dict[str, Any]]:
    from questbank.types.canonical import CompositeVisualOptions, ImageBlock, MixedOptions

    rows: list[dict[str, Any]] = []
    assets: list[tuple[str, str | None, str | None]] = []  # name, role, option_label

    for block in record.content:
        if isinstance(block, ImageBlock) and block.asset:
            assets.append((block.asset, "stem", None))

    opts = record.options
    if isinstance(opts, CompositeVisualOptions) and opts.asset:
        assets.append((opts.asset, "options", None))
    elif isinstance(opts, MixedOptions) and opts.asset:
        assets.append((opts.asset, "options", None))

    key = paper_identity.source_key_for(record.question_ref).replace("|", "_")
    for index, (name, role, option_label) in enumerate(assets):
        path = assets_dir / name
        if not path.exists():
            logger.warning("Skipping missing asset for %s: %s", record.question_ref, name)
            continue
        png_bytes = path.read_bytes()
        storage_path = f"exam_questions/{key}/{name}"
        public_url = upload_question_png(
            client,
            storage_path=storage_path,
            png_bytes=png_bytes,
        )
        width = height = None
        try:
            from io import BytesIO

            from PIL import Image

            with Image.open(BytesIO(png_bytes)) as img:
                width, height = img.size
        except Exception:  # noqa: BLE001
            pass
        rows.append(
            map_media_row(
                question_id=question_id,
                storage_path=storage_path,
                public_url=public_url,
                page_number=record.source_page,
                image_index=index,
                width=width,
                height=height,
                bbox=None,
                role=role,
                option_label=option_label,
            )
        )
    return rows
