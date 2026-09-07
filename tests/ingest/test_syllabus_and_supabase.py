from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from questbank.integrations.supabase_store import map_option_rows, map_question_row, push_mcq_bank
from questbank.syllabus.classify_mcq import classify_question
from questbank.syllabus.parse_syllabus_pdf import (
    SyllabusSubtopic,
    SyllabusTaxonomy,
    SyllabusTopic,
    parse_syllabus_text,
)
from questbank.types.ingest import (
    PaperIdentity,
    QuestionRecord,
    TopicClassification,
    question_ref_from_number,
)
from questbank.types.layout import BoundingBox
from questbank.types.question import (
    ParsedOption,
    ParsedQuestion,
    SourceRegion,
    VisualExpectation,
)

IDENTITY = PaperIdentity(source_exam_year=2023, paper_code="6092/01", paper_type="mcq")

SYLLABUS_FIXTURE = """
CONTENT STRUCTURE
Sections Topics
I. Matter - Structures and Properties
1. Experimental Chemistry
2. The Particulate Nature of Matter
3. Chemical Bonding and Structure

SUBJECT CONTENT
SECTION I: MATTER - STRUCTURES AND PROPERTIES

1. Experimental Chemistry
Content
1.1 Experimental Design
1.2 Methods of Purification and Analysis
Learning Outcomes
Candidates should be able to:
(a) name appropriate apparatus for measurement
(b) describe methods of separation including filtration crystallisation distillation chromatography

2. The Particulate Nature of Matter
Content
2.1 Kinetic Particle Theory
2.2 Atomic Structure
Learning Outcomes
Candidates should be able to:
(a) describe solid liquid gaseous states diffusion
(e) define the term isotopes
(f) deduce protons neutrons electrons in atoms and ions
"""


def test_parse_syllabus_text_topics_and_subtopics():
    taxonomy = parse_syllabus_text(SYLLABUS_FIXTURE)
    numbers = [t.number for t in taxonomy.topics]
    assert 1 in numbers and 2 in numbers
    by_num = {t.number: t for t in taxonomy.topics}
    codes = {s.code for s in by_num[1].subtopics} | {s.code for s in by_num[2].subtopics}
    assert "1.1" in codes or "1.2" in codes
    assert "2.2" in codes


def test_classifier_maps_isotopes_to_atomic_structure():
    taxonomy = parse_syllabus_text(SYLLABUS_FIXTURE)
    record = _record(
        7,
        stem="An atom of an isotope of chlorine has 17 protons and 20 neutrons. How many electrons?",
        options={"A": "17", "B": "20", "C": "37", "D": "3"},
    )
    result = classify_question(record, taxonomy)
    assert result.syllabus_code is not None
    assert "2.2" in (result.syllabus_code or "")
    assert result.topic_match_method == "keyword_overlap"
    assert result.topic_confidence is not None and result.topic_confidence > 0


def test_map_visual_option_uses_placeholder_text():
    record = _record(
        4,
        stem="Which apparatus?",
        options={"A": "", "B": "", "C": "", "D": ""},
        correct="A",
    )
    for label in ("A", "B", "C", "D"):
        record.question.options[label].requires_visual = True
        record.question.options[label].text = None
    options = map_option_rows(record, question_id="q-4")
    assert all(o["text"] == "[visual option]" for o in options)
    assert sum(1 for o in options if o["is_correct"]) == 1


def test_map_question_and_options_include_correct_answer():
    record = _record(
        1,
        stem="Which apparatus?",
        options={"A": "beaker", "B": "burette", "C": "pipette", "D": "flask"},
        correct="B",
        topic=TopicClassification(
            topic="Experimental Design",
            parent_topic="Experimental Chemistry",
            subject="Chemistry",
            syllabus_code="6092:1.1",
            topic_confidence=0.4,
            topic_match_reasoning="test",
            topic_match_method="keyword_overlap",
            status="ok",
        ),
    )
    row = map_question_row(record, bank_id="bank-1", question_id="q-1")
    assert row["correct_answer"] == "B"
    assert row["topic"] == "Experimental Design"
    assert row["syllabus_code"] == "6092:1.1"
    options = map_option_rows(record, question_id="q-1")
    assert len(options) == 4
    assert sum(1 for o in options if o["is_correct"]) == 1
    assert next(o for o in options if o["label"] == "B")["is_correct"] is True


def test_push_mcq_bank_mocked_client():
    taxonomy = SyllabusTaxonomy(
        topics=[
            SyllabusTopic(
                number=2,
                title="The Particulate Nature of Matter",
                subtopics=[SyllabusSubtopic(code="2.2", title="Atomic Structure")],
            )
        ]
    )
    record = _record(
        1,
        stem="Isotopes have same proton number",
        options={"A": "true", "B": "false", "C": "maybe", "D": "never"},
        correct="A",
        topic=TopicClassification(
            topic="Atomic Structure",
            parent_topic="The Particulate Nature of Matter",
            syllabus_code="6092:2.2",
            topic_confidence=0.5,
            topic_match_method="keyword_overlap",
            topic_match_reasoning="test",
            status="ok",
        ),
    )

    class FakeQuery:
        def __init__(self, store, table):
            self.store = store
            self.table_name = table
            self._action = None
            self._payload = None
            self._filters = {}

        def select(self, *_a, **_k):
            self._action = "select"
            return self

        def insert(self, payload):
            self._action = "insert"
            self._payload = payload
            return self

        def update(self, payload):
            self._action = "update"
            self._payload = payload
            return self

        def delete(self):
            self._action = "delete"
            return self

        def eq(self, key, value):
            self._filters[key] = value
            return self

        def in_(self, key, values):
            self._filters[f"in:{key}"] = list(values)
            return self

        def limit(self, *_a, **_k):
            return self

        def execute(self):
            table = self.store.setdefault(self.table_name, [])
            if self._action == "select":
                rows = table
                for key, value in self._filters.items():
                    if key.startswith("in:"):
                        field = key.split(":", 1)[1]
                        rows = [r for r in rows if r.get(field) in value]
                    else:
                        rows = [r for r in rows if r.get(key) == value]
                return SimpleNamespace(data=rows)
            if self._action == "insert":
                payload = self._payload if isinstance(self._payload, list) else [self._payload]
                table.extend(payload)
                return SimpleNamespace(data=payload)
            if self._action == "update":
                for row in table:
                    if all(row.get(k) == v for k, v in self._filters.items() if not k.startswith("in:")):
                        row.update(self._payload)
                return SimpleNamespace(data=[])
            if self._action == "delete":
                keep = []
                for row in table:
                    drop = False
                    for key, value in self._filters.items():
                        if key.startswith("in:"):
                            field = key.split(":", 1)[1]
                            if row.get(field) in value:
                                drop = True
                        elif row.get(key) == value:
                            drop = True
                    if not drop:
                        keep.append(row)
                self.store[self.table_name] = keep
                return SimpleNamespace(data=[])
            return SimpleNamespace(data=[])

    class FakeClient:
        def __init__(self):
            self.store: dict = {}

        def table(self, name):
            return FakeQuery(self.store, name)

    client = FakeClient()
    result = push_mcq_bank(
        records=[record],
        paper_identity=IDENTITY,
        bank_name="unit-test-bank",
        source_files=["a.pdf"],
        taxonomy=taxonomy,
        client=client,
    )
    assert result["questions"] == 1
    assert result["options"] == 4
    assert len(client.store["question_banks"]) == 1
    assert len(client.store["questions"]) == 1
    assert client.store["questions"][0]["correct_answer"] == "A"
    assert sum(1 for o in client.store["question_options"] if o["is_correct"]) == 1


def _record(
    number: int,
    *,
    stem: str,
    options: dict[str, str],
    correct: str | None = None,
    topic: TopicClassification | None = None,
) -> QuestionRecord:
    qref = question_ref_from_number(number)
    question = ParsedQuestion(
        question_number=number,
        source=SourceRegion(
            page_start=1,
            page_end=1,
            bounding_box=BoundingBox(x0=0, y0=0, x1=10, y1=10),
        ),
        stem=stem,
        options={
            label: ParsedOption(label=label, text=text, requires_visual=False)
            for label, text in options.items()
        },
        visual=VisualExpectation(required=False, extraction_pending=False),
        validation={"status": "pass", "issues": []},
    )
    return QuestionRecord(
        paper_identity=IDENTITY,
        source_key=IDENTITY.source_key_for(qref),
        question_ref=qref,
        source_regions=[question.source],
        question=question,
        correct_option=correct,  # type: ignore[arg-type]
        topic_classification=topic,
    )
