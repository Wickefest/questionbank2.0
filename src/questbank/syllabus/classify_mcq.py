from __future__ import annotations

import math
import re
from collections import Counter

from questbank.syllabus.parse_syllabus_pdf import SyllabusTaxonomy, SyllabusTopic, SyllabusSubtopic
from questbank.types.ingest import QuestionRecord, TopicClassification
from questbank.types.question import OPTION_LABELS

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "from",
        "by",
        "is",
        "are",
        "be",
        "as",
        "at",
        "that",
        "this",
        "these",
        "those",
        "which",
        "what",
        "when",
        "where",
        "how",
        "why",
        "not",
        "no",
        "yes",
        "can",
        "may",
        "will",
        "would",
        "should",
        "could",
        "into",
        "using",
        "used",
        "use",
        "given",
        "following",
        "shown",
        "diagram",
        "figure",
        "table",
        "question",
        "answer",
        "option",
        "options",
        "correct",
        "statement",
        "about",
        "between",
        "each",
        "all",
        "both",
        "only",
        "same",
        "different",
        "one",
        "two",
        "three",
        "four",
        "most",
        "least",
        "more",
        "less",
        "than",
        "during",
        "after",
        "before",
        "under",
        "over",
        "per",
        "via",
        "such",
        "include",
        "includes",
        "including",
    }
)

# Extra weight for distinctive chemistry tokens that appear in syllabus titles.
_BOOST = {
    "isotope": 3.0,
    "isotopes": 3.0,
    "nucleon": 3.0,
    "proton": 2.0,
    "neutron": 2.0,
    "electron": 1.5,
    "chromatography": 3.5,
    "distillation": 3.0,
    "filtration": 2.5,
    "crystallisation": 2.5,
    "crystallization": 2.5,
    "diffusion": 3.0,
    "ionic": 2.5,
    "covalent": 2.5,
    "metallic": 2.0,
    "mole": 3.0,
    "moles": 3.0,
    "stoichiometry": 3.0,
    "titration": 3.0,
    "acid": 2.0,
    "alkali": 2.5,
    "base": 1.5,
    "ph": 2.5,
    "redox": 3.5,
    "oxidation": 3.0,
    "reduction": 3.0,
    "oxidising": 3.0,
    "oxidizing": 3.0,
    "reducing": 3.0,
    "electrolysis": 3.5,
    "electrode": 2.5,
    "periodic": 2.5,
    "halogen": 3.0,
    "halogens": 3.0,
    "enthalpy": 3.5,
    "exothermic": 3.0,
    "endothermic": 3.0,
    "catalyst": 3.0,
    "rate": 1.5,
    "alkane": 3.0,
    "alkene": 3.0,
    "alcohol": 2.5,
    "carboxylic": 3.0,
    "polymer": 3.0,
    "cracking": 3.0,
    "fractional": 2.5,
    "atmosphere": 2.5,
    "pollutant": 3.0,
    "ozone": 3.0,
    "greenhouse": 3.0,
}

_LOW_CONFIDENCE = 0.12


def classify_records(
    records: list[QuestionRecord],
    taxonomy: SyllabusTaxonomy,
) -> list[QuestionRecord]:
    return [
        record.model_copy(update={"topic_classification": classify_question(record, taxonomy)})
        for record in records
    ]


def classify_question(
    record: QuestionRecord,
    taxonomy: SyllabusTaxonomy,
) -> TopicClassification:
    text = _question_text(record)
    tokens = _tokenize(text)
    if not tokens or not taxonomy.topics:
        return TopicClassification(
            subject=taxonomy.subject,
            syllabus_code=taxonomy.syllabus_code,
            topic_match_method="keyword_overlap",
            topic_match_reasoning="No question tokens or empty taxonomy",
            topic_confidence=0.0,
            status="needs_review",
        )

    q_counts = Counter(tokens)
    best_score = 0.0
    best: tuple[SyllabusTopic, SyllabusSubtopic | None] | None = None
    best_hits: list[str] = []

    for topic, sub in _candidates(taxonomy):
        corpus = _corpus_tokens(topic, sub)
        if not corpus:
            continue
        score, hits = _score(q_counts, corpus)
        if score > best_score:
            best_score = score
            best = (topic, sub)
            best_hits = hits

    if best is None or best_score <= 0:
        return TopicClassification(
            subject=taxonomy.subject,
            syllabus_code=taxonomy.syllabus_code,
            topic_match_method="keyword_overlap",
            topic_match_reasoning="No overlapping syllabus keywords",
            topic_confidence=0.0,
            status="needs_review",
        )

    topic, sub = best
    confidence = _normalize_confidence(best_score, q_counts)
    if sub is not None:
        code = f"{taxonomy.syllabus_code}:{sub.code}"
        topic_title = sub.title
        parent = topic.title
        reasoning = (
            f"Best subtopic {sub.code} '{sub.title}' under topic {topic.number} "
            f"'{topic.title}' (score={best_score:.2f}; hits={', '.join(best_hits[:8]) or 'n/a'})"
        )
    else:
        code = f"{taxonomy.syllabus_code}:{topic.number}"
        topic_title = topic.title
        parent = topic.section
        reasoning = (
            f"Best topic {topic.number} '{topic.title}' "
            f"(score={best_score:.2f}; hits={', '.join(best_hits[:8]) or 'n/a'})"
        )

    status = "ok" if confidence >= _LOW_CONFIDENCE else "needs_review"
    return TopicClassification(
        topic=topic_title,
        parent_topic=parent,
        subject=taxonomy.subject,
        syllabus_code=code,
        topic_confidence=round(confidence, 4),
        topic_match_reasoning=reasoning,
        topic_match_method="keyword_overlap",
        status=status,
    )


def _candidates(
    taxonomy: SyllabusTaxonomy,
) -> list[tuple[SyllabusTopic, SyllabusSubtopic | None]]:
    pairs: list[tuple[SyllabusTopic, SyllabusSubtopic | None]] = []
    for topic in taxonomy.topics:
        if topic.subtopics:
            for sub in topic.subtopics:
                pairs.append((topic, sub))
        else:
            pairs.append((topic, None))
    return pairs


def _question_text(record: QuestionRecord) -> str:
    question = record.question
    parts = [question.stem or ""]
    for label in OPTION_LABELS:
        option = question.options.get(label)
        if option and option.text:
            parts.append(option.text)
    return "\n".join(parts)


def _tokenize(text: str) -> list[str]:
    return [tok for tok in _TOKEN.findall((text or "").lower()) if tok not in _STOP and len(tok) > 1]


def _corpus_tokens(topic: SyllabusTopic, sub: SyllabusSubtopic | None) -> Counter[str]:
    blobs = [topic.title, topic.section or ""]
    if sub is not None:
        blobs.extend([sub.title, sub.outcomes_text])
    counts: Counter[str] = Counter()
    for blob in blobs:
        for tok in _tokenize(blob):
            weight = _BOOST.get(tok, 1.0)
            # Title tokens get a mild bump.
            if blob in {topic.title, sub.title if sub else ""}:
                weight *= 1.4
            counts[tok] += weight
    return counts


def _score(q_counts: Counter[str], corpus: Counter[str]) -> tuple[float, list[str]]:
    score = 0.0
    hits: list[str] = []
    for tok, q_weight in q_counts.items():
        if tok not in corpus:
            continue
        boost = _BOOST.get(tok, 1.0)
        contrib = math.sqrt(q_weight) * corpus[tok] * boost
        score += contrib
        hits.append(tok)
    hits.sort(key=lambda t: (-_BOOST.get(t, 1.0), t))
    return score, hits


def _normalize_confidence(score: float, q_counts: Counter[str]) -> float:
    # Soft saturation so strong keyword hits land around 0.2–0.9.
    denom = max(8.0, math.sqrt(sum(q_counts.values())) * 3.0)
    return max(0.0, min(0.99, score / (score + denom)))
