"""Phase 1 Chemistry Paper 1 question parser."""

from questbank.parsers.chemistry.parse_mcq_paper import parse_chemistry_paper_1
from questbank.types.question import ParsedPaper, ParsedQuestion

__all__ = ["parse_chemistry_paper_1", "ParsedPaper", "ParsedQuestion"]
