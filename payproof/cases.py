"""In-memory workflow: extract frozen sources, explicitly review, and compare."""

from datetime import UTC, datetime
from uuid import uuid4

from payproof.comparison import compare
from payproof.config import Settings
from payproof.extraction import extract_documents
from payproof.normalization import NormalizationError, canonical_iban
from payproof.schemas import (
    CaseContract,
    NormalizedPaymentIdentity,
    PaymentRequestEvidence,
    SourceDocument,
    SourceReview,
    TrustedVendorRecord,
)


def start_case(
    baseline: TrustedVendorRecord,
    sources: tuple[SourceDocument, ...],
    *,
    settings: Settings,
) -> CaseContract:
    """Extract only after validating the selected baseline and its prior chronology."""
    baseline = TrustedVendorRecord.model_validate(baseline.model_dump())
    if not sources or baseline.last_verified_at >= min(s.captured_at for s in sources):
        raise ValueError("trusted baseline must predate every source capture")
    evidence = extract_documents(sources, settings=settings)
    return CaseContract(sources=sources, evidence=evidence, baseline=baseline)


def candidate_identity(evidence: PaymentRequestEvidence) -> NormalizedPaymentIdentity | None:
    """Normalize all observations; never select one of conflicting/invalid accounts.

    This is a representation preview, not a human review or comparison result.
    """
    accounts = evidence.account_identifier
    if accounts.status not in ("FOUND", "AMBIGUOUS"):
        return None
    try:
        values = {canonical_iban(candidate.value) for candidate in accounts.candidates}
    except NormalizationError:
        return None
    if len(values) != 1:
        return None
    return NormalizedPaymentIdentity(
        normalization_version="iban-gb-de-v1",
        scheme="IBAN",
        raw_account_identifier=accounts.candidates[0].value,
        account_identifier=values.pop(),
    )


def review_case(
    case: CaseContract,
    *,
    operator_id: str,
    destination_instructions_checked: bool,
) -> CaseContract:
    """Record an explicit acknowledgement after displaying all sources and spans.

    The caller controls the local human action. This records source review only;
    independent verification via the trusted contact is a separate future command.
    """
    case = CaseContract.model_validate(case.model_dump())
    if destination_instructions_checked is not True:
        raise ValueError("source review requires explicit acknowledgement")
    if case.review is not None or case.comparison is not None or case.verification is not None:
        raise ValueError("source review requires a fresh snapshot")
    if case.evidence.extraction.failure_code:
        raise ValueError("failed extraction cannot receive a successful source review")
    review = SourceReview(
        review_id=uuid4(),
        request_id=case.evidence.request_id,
        attempt_id=case.evidence.extraction.attempt_id,
        operator_id=operator_id,
        reviewed_at=datetime.now(UTC),
        destination_instructions_checked=True,
        reviewed_evidence_ids=tuple(span.evidence_id for span in case.evidence.spans()),
        payment_identity=candidate_identity(case.evidence),
    )
    return CaseContract(
        sources=case.sources,
        evidence=case.evidence,
        baseline=case.baseline,
        review=review,
    )


def complete_case(case: CaseContract) -> CaseContract:
    """Attach an authoritative comparison without manufacturing a human review."""
    result = compare(case, comparison_id=uuid4(), compared_at=datetime.now(UTC))
    return CaseContract(
        sources=case.sources,
        evidence=case.evidence,
        baseline=case.baseline,
        review=case.review,
        comparison=result,
    )
