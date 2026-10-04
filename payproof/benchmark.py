"""Corpus-validation runner; no unimplemented comparison or AI accuracy claims."""

from collections import Counter
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from payproof.fixtures import load_corpus


@dataclass(frozen=True)
class CorpusValidationReport:
    scope: Literal["schema_and_source_validation"]
    vendors_validated: int
    requests_validated: int
    expected_outcomes: dict[str, int]
    comparison_evaluation: Literal["NOT_IMPLEMENTED"]
    ai_evaluation: Literal["NOT_IMPLEMENTED"]
    elapsed_ms: float


def validate_corpus() -> CorpusValidationReport:
    started = perf_counter()
    corpus = load_corpus()
    return CorpusValidationReport(
        scope="schema_and_source_validation",
        vendors_validated=len(corpus.vendors),
        requests_validated=len(corpus.requests),
        expected_outcomes=dict(Counter(r.expected_state_after_review for r in corpus.requests)),
        comparison_evaluation="NOT_IMPLEMENTED",
        ai_evaluation="NOT_IMPLEMENTED",
        elapsed_ms=round((perf_counter() - started) * 1000, 3),
    )
