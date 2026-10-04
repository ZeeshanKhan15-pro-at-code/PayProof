"""Pure source-bound Phase-1 decision engine. No provider, storage, clock, or RNG."""

from datetime import datetime
from uuid import UUID

from payproof.normalization import NormalizationError, canonical_iban, canonical_scheme
from payproof.schemas import (
    CaseContract,
    ComparisonResult,
    ComparisonState,
    Contradiction,
    EvidenceField,
    ExtractedField,
    FieldDifference,
    MissingInformation,
    ReasonCode,
)

# Stable gate ordering. Return all observed blockers, with the primary blocker first.
UNCERTAINTY_ORDER: tuple[ReasonCode, ...] = (
    "BASELINE_UNAVAILABLE",
    "BASELINE_INVALID",
    "EXTRACTION_FAILED",
    "EVIDENCE_INVALID",
    "REVIEW_REQUIRED",
    "DESTINATION_MISSING",
    "DESTINATION_INCOMPLETE",
    "UNSUPPORTED_DESTINATION",
    "DESTINATION_INVALID",
    "DESTINATION_AMBIGUOUS",
)


def _evidence_ids(field: ExtractedField[str]) -> tuple[UUID, ...]:
    return tuple(c.evidence.evidence_id for c in field.candidates)


def _raw_value(field: ExtractedField[str]) -> str | None:
    # Multiple identical raw observations may supply context; differing ones do not.
    values = {c.value for c in field.candidates}
    return next(iter(values)) if len(values) == 1 else None


def _difference(
    field: EvidenceField,
    baseline: str | None,
    requested: str | None,
    evidence_ids: tuple[UUID, ...],
) -> FieldDifference:
    return FieldDifference(
        field=field,
        baseline_value=baseline,
        requested_value=requested,
        status=(
            "UNKNOWN"
            if baseline is None or requested is None
            else "MATCH"
            if baseline == requested
            else "CHANGED"
        ),
        evidence_ids=evidence_ids,
    )


def compare(
    case: CaseContract,
    *,
    comparison_id: UUID,
    compared_at: datetime,
    selected_vendor_id: UUID | None = None,
) -> ComparisonResult:
    """Compare frozen snapshots after explicit review; metadata comes from the caller.

    A missing baseline requires the caller's manually selected vendor ID. Invalid
    contracts/chronology are rejected before any result is returned. No human
    review or verification record is manufactured by this function.
    """
    # Revalidate even constructed/copied Pydantic objects and nested snapshots.
    case = CaseContract.model_validate(case.model_dump())
    if case.comparison is not None or case.verification is not None:
        raise ValueError("comparison requires a fresh snapshot without a prior result")
    baseline, evidence, review = case.baseline, case.evidence, case.review
    if baseline is None and selected_vendor_id is None:
        raise ValueError("missing baseline requires an explicit selected vendor ID")
    if baseline and selected_vendor_id is not None and selected_vendor_id != baseline.vendor_id:
        raise ValueError("selected vendor must match the frozen baseline")
    vendor_id = baseline.vendor_id if baseline else selected_vendor_id
    assert vendor_id is not None

    blockers: set[ReasonCode] = set()
    missing: list[MissingInformation] = []
    contradictions: list[Contradiction] = []
    if baseline is None:
        blockers.add("BASELINE_UNAVAILABLE")
        missing.append(
            MissingInformation(
                field="account_identifier",
                side="BASELINE",
                explanation="No previously trusted vendor baseline snapshot is available.",
            )
        )
    failure = evidence.extraction.failure_code
    if failure:
        blockers.add("EVIDENCE_INVALID" if failure == "EVIDENCE_INVALID" else "EXTRACTION_FAILED")
    elif review is None:
        blockers.add("REVIEW_REQUIRED")

    accounts = evidence.account_identifier
    canonical_accounts: set[str] = set()
    for candidate in accounts.candidates:
        try:
            canonical_accounts.add(canonical_iban(candidate.value))
        except NormalizationError as error:
            blockers.add(error.reason_code)
    valid_accounts = len(canonical_accounts) == 1 and not blockers.intersection(
        ("DESTINATION_INCOMPLETE", "UNSUPPORTED_DESTINATION", "DESTINATION_INVALID")
    )
    canonical_account = next(iter(canonical_accounts)) if valid_accounts else None
    if accounts.status in ("MISSING", "UNREADABLE"):
        blockers.add(
            "DESTINATION_MISSING" if accounts.status == "MISSING" else "DESTINATION_INCOMPLETE"
        )
        missing.append(
            MissingInformation(
                field="account_identifier",
                side="REQUEST",
                explanation="Requested account is absent or unreadable; no value was inferred.",
            )
        )
    elif accounts.status == "UNSUPPORTED":
        blockers.add("UNSUPPORTED_DESTINATION")
    elif accounts.status == "AMBIGUOUS" and not valid_accounts:
        blockers.add("DESTINATION_AMBIGUOUS")
        contradictions.append(
            Contradiction(
                field="account_identifier",
                explanation="Account observations cannot resolve to one complete supported IBAN.",
                evidence_ids=_evidence_ids(accounts),
            )
        )

    schemes = evidence.destination_scheme
    canonical_schemes: set[str] = set()
    invalid_scheme = False
    for candidate in schemes.candidates:
        try:
            canonical_schemes.add(canonical_scheme(candidate.value))
        except ValueError:
            invalid_scheme = True
            blockers.add("UNSUPPORTED_DESTINATION")
    if schemes.status == "UNREADABLE":
        blockers.add("DESTINATION_INCOMPLETE")
        missing.append(
            MissingInformation(
                field="destination_scheme",
                side="REQUEST",
                explanation="Explicit destination scheme could not be read.",
            )
        )
    elif schemes.status == "UNSUPPORTED" or any(s != "IBAN" for s in canonical_schemes):
        blockers.add("UNSUPPORTED_DESTINATION")
    if schemes.status == "AMBIGUOUS" and (canonical_schemes != {"IBAN"} or invalid_scheme):
        blockers.add("DESTINATION_AMBIGUOUS")
        contradictions.append(
            Contradiction(
                field="destination_scheme",
                explanation="Destination scheme observations remain unresolved.",
                evidence_ids=_evidence_ids(schemes),
            )
        )

    routing = evidence.routing_identifier
    if routing.status in ("FOUND", "AMBIGUOUS", "UNSUPPORTED") or (
        baseline and baseline.routing_identifier is not None
    ):
        blockers.add("UNSUPPORTED_DESTINATION")
    if routing.status == "UNREADABLE":
        blockers.add("DESTINATION_INCOMPLETE")
        missing.append(
            MissingInformation(
                field="routing_identifier",
                side="REQUEST",
                explanation="Separate routing instructions are unreadable and unsupported.",
            )
        )
    if routing.status == "AMBIGUOUS" and len({c.value for c in routing.candidates}) > 1:
        blockers.add("DESTINATION_AMBIGUOUS")
        contradictions.append(
            Contradiction(
                field="routing_identifier",
                explanation="Separate routing observations differ; no equivalences are assumed.",
                evidence_ids=_evidence_ids(routing),
            )
        )

    if review and not failure:
        destination_ids = set(
            _evidence_ids(accounts) + _evidence_ids(schemes) + _evidence_ids(routing)
        )
        if not destination_ids.issubset(review.reviewed_evidence_ids) or (
            canonical_account is not None and review.payment_identity is None
        ):
            blockers.add("REVIEW_REQUIRED")

    # Raw contextual differences explain observations; they never select a state.
    contexts: tuple[tuple[EvidenceField, str | None, ExtractedField[str]], ...] = (
        ("vendor_name", baseline.canonical_vendor_name if baseline else None, evidence.vendor_name),
        ("sender_email", baseline.trusted_email if baseline else None, evidence.sender_email),
        ("bank_name", baseline.bank_name if baseline else None, evidence.bank_name),
        ("currency", baseline.currency if baseline else None, evidence.currency),
    )
    differences = [
        _difference(name, prior, _raw_value(observed), _evidence_ids(observed))
        for name, prior, observed in contexts
    ]
    for name, _, observed in contexts:
        if observed.status == "AMBIGUOUS" and len({c.value for c in observed.candidates}) > 1:
            contradictions.append(
                Contradiction(
                    field=name,
                    explanation="Contextual observations differ; destination equality is unaffected.",
                    evidence_ids=_evidence_ids(observed),
                )
            )
    differences.extend(
        (
            _difference(
                "account_identifier",
                baseline.payment_identity.account_identifier if baseline else None,
                canonical_account,
                _evidence_ids(accounts),
            ),
            _difference(
                "routing_identifier",
                baseline.routing_identifier if baseline else None,
                _raw_value(routing),
                _evidence_ids(routing),
            ),
            _difference(
                "destination_scheme",
                baseline.payment_identity.scheme if baseline else None,
                _raw_value(schemes),
                _evidence_ids(schemes),
            ),
        )
    )
    state: ComparisonState = "UNCERTAIN"
    reasons = tuple(reason for reason in UNCERTAINTY_ORDER if reason in blockers)
    if not reasons:
        assert baseline is not None and review is not None and review.payment_identity is not None
        if canonical_account == baseline.payment_identity.account_identifier:
            state, reasons = "UNCHANGED", ("DESTINATION_MATCH",)
        else:
            state, reasons = "VERIFY", ("DESTINATION_CHANGED",)
    result = ComparisonResult(
        comparison_id=comparison_id,
        request_id=evidence.request_id,
        vendor_id=vendor_id,
        baseline_revision_id=baseline.revision_id if baseline else None,
        review_id=review.review_id if review else None,
        rule_version="iban-gb-de-v1",
        compared_at=compared_at,
        state=state,
        baseline_identity=baseline.payment_identity if baseline else None,
        requested_identity=review.payment_identity if review else None,
        differences=tuple(differences),
        missing_information=tuple(missing),
        contradictions=tuple(contradictions),
        evidence_ids=tuple(span.evidence_id for span in evidence.spans()),
        reason_codes=reasons,
    )
    CaseContract(
        sources=case.sources,
        evidence=evidence,
        baseline=baseline,
        review=review,
        comparison=result,
    )
    return result
