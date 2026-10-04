"""Offline comparison on labeled synthetic evidence with simulated source reviews."""

from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from time import perf_counter
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from payproof.comparison import compare
from payproof.fixtures import load_corpus
from payproof.normalization import NormalizationError, canonical_iban
from payproof.schemas import CaseContract, NormalizedPaymentIdentity, SourceReview


@dataclass(frozen=True)
class CorpusValidationReport:
    scope: Literal["synthetic_gold_comparison"]
    vendors_validated: int
    requests_validated: int
    expected_outcomes: dict[str, int]
    comparison_evaluation: Literal["PASS", "FAIL"]
    comparisons_evaluated: int
    comparison_mismatches: tuple[str, ...]
    false_unchanged: int
    review_mode: Literal["SIMULATED_FIXTURE_REVIEW"]
    release_corpus_complete: Literal[False]
    ai_evaluation: Literal["NOT_IMPLEMENTED"]
    elapsed_ms: float


def validate_corpus() -> CorpusValidationReport:
    started = perf_counter()
    corpus = load_corpus()
    mismatches: list[str] = []
    false_unchanged = 0
    for request in corpus.requests:
        baseline = next(v for v in corpus.vendors if v.revision_id == request.baseline_revision_id)
        candidates = request.evidence.account_identifier.candidates
        identity = None
        if request.evidence.account_identifier.status == "FOUND":
            try:
                canonical = canonical_iban(candidates[0].value)
            except NormalizationError:
                pass
            else:
                identity = NormalizedPaymentIdentity(
                    normalization_version="iban-gb-de-v1",
                    scheme="IBAN",
                    raw_account_identifier=candidates[0].value,
                    account_identifier=canonical,
                )
        # Benchmark-only simulation, never a runtime approval or human verification.
        reviewed_at = request.evidence.extraction.extracted_at + timedelta(minutes=1)
        review = SourceReview(
            review_id=uuid5(NAMESPACE_URL, f"payproof:benchmark:review:{request.fixture_id}"),
            request_id=request.evidence.request_id,
            attempt_id=request.evidence.extraction.attempt_id,
            operator_id="synthetic-benchmark-review-simulation",
            reviewed_at=reviewed_at,
            destination_instructions_checked=True,
            reviewed_evidence_ids=tuple(s.evidence_id for s in request.evidence.spans()),
            payment_identity=identity,
        )
        result = compare(
            CaseContract(
                sources=(request.source,),
                evidence=request.evidence,
                baseline=baseline,
                review=review,
            ),
            comparison_id=uuid5(
                NAMESPACE_URL, f"payproof:benchmark:comparison:{request.fixture_id}"
            ),
            compared_at=reviewed_at + timedelta(minutes=1),
        )
        if (
            result.state != request.expected_state_after_review
            or result.reason_codes != request.expected_reason_codes
        ):
            mismatches.append(request.fixture_id)
        if result.state == "UNCHANGED" and request.expected_state_after_review != "UNCHANGED":
            false_unchanged += 1
    return CorpusValidationReport(
        scope="synthetic_gold_comparison",
        vendors_validated=len(corpus.vendors),
        requests_validated=len(corpus.requests),
        expected_outcomes=dict(Counter(r.expected_state_after_review for r in corpus.requests)),
        comparison_evaluation="FAIL" if mismatches else "PASS",
        comparisons_evaluated=len(corpus.requests),
        comparison_mismatches=tuple(mismatches),
        false_unchanged=false_unchanged,
        review_mode="SIMULATED_FIXTURE_REVIEW",
        release_corpus_complete=False,
        ai_evaluation="NOT_IMPLEMENTED",
        elapsed_ms=round((perf_counter() - started) * 1000, 3),
    )
