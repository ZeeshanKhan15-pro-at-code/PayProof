"""Design-only benchmark contracts; no predictions, provider calls, or scoring."""

from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from payproof.schemas import (
    CaseContract,
    ComparisonState,
    Contract,
    EvidenceField,
    NormalizedPaymentIdentity,
    PaymentRequestEvidence,
    ReasonCode,
    ShortText,
    SourceDocument,
    SourceLocation,
    SourceReview,
    Text,
    TrustedVendorRecord,
)


class BenchmarkBaseline(Contract):
    key: ShortText
    record: TrustedVendorRecord

    @model_validator(mode="after")
    def synthetic_provenance(self) -> "BenchmarkBaseline":
        if (
            self.record.provenance.source_kind != "SYNTHETIC_FIXTURE"
            or self.record.callback_contact.provenance.source_kind != "SYNTHETIC_FIXTURE"
        ):
            raise ValueError("diagnostic baselines and callbacks must be synthetic")
        return self


class ConsequentialChange(Contract):
    component: Literal[
        "iban_account_component",
        "iban_routing_component",
        "iban_bank_component",
        "separate_routing_identifier",
        "country",
    ]
    trusted_value: ShortText
    requested_value: ShortText

    @model_validator(mode="after")
    def distinct_values(self) -> "ConsequentialChange":
        if self.trusted_value == self.requested_value:
            raise ValueError("a consequential change requires distinct values")
        return self


class BenchmarkTruth(Contract):
    destination_relation: Literal["CHANGED", "UNCHANGED", "UNRESOLVED"]
    consequential_changes: tuple[ConsequentialChange, ...]
    contextual_changes: tuple[EvidenceField, ...]
    phase1_comparable: bool
    boundary: Literal[
        "SUPPORTED",
        "SEPARATE_ROUTING",
        "INVALID_REPRESENTATION",
        "INSUFFICIENT_INFORMATION",
        "MISSING_TRUSTED_HISTORY",
        "UNSUPPORTED_COUNTRY",
    ]
    rationale: Text

    @model_validator(mode="after")
    def labels_are_consistent(self) -> "BenchmarkTruth":
        if (self.destination_relation == "CHANGED") != bool(self.consequential_changes):
            raise ValueError("only a known change may list consequential differences")
        if self.phase1_comparable != (self.boundary == "SUPPORTED"):
            raise ValueError("comparability must agree with the scope boundary")
        if self.destination_relation == "UNRESOLVED" and self.phase1_comparable:
            raise ValueError("unresolved truth cannot be comparable")
        if len({c.component for c in self.consequential_changes}) != len(
            self.consequential_changes
        ):
            raise ValueError("consequential components must be unique")
        if len(set(self.contextual_changes)) != len(self.contextual_changes) or set(
            self.contextual_changes
        ).intersection(("account_identifier", "routing_identifier", "destination_scheme")):
            raise ValueError("context changes must be unique and non-destination fields")
        return self


class BenchmarkExpectation(Contract):
    state: ComparisonState
    reason_codes: Annotated[tuple[ReasonCode, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def valid_reasons(self) -> "BenchmarkExpectation":
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("expected reasons must be unique")
        decisive = set(self.reason_codes).intersection(("DESTINATION_MATCH", "DESTINATION_CHANGED"))
        if self.state == "UNCERTAIN":
            if decisive:
                raise ValueError("uncertainty cannot have a decisive reason")
        elif self.reason_codes != (
            "DESTINATION_MATCH" if self.state == "UNCHANGED" else "DESTINATION_CHANGED",
        ):
            raise ValueError("decisive states require their singleton reason")
        return self


class NonDestinationSpan(Contract):
    source_id: UUID
    role: Literal["HISTORICAL_DESTINATION", "IRRELEVANT_NUMBER"]
    raw_value: Text
    exact_excerpt: Annotated[str, Field(min_length=1, max_length=20_000)]
    location: SourceLocation


class BenchmarkCase(Contract):
    case_id: Annotated[str, Field(pattern=r"^PP-[0-9]{2}$")]
    title: ShortText
    coverage_bucket: Literal["TRUE_CHANGE", "NO_CONSEQUENTIAL_CHANGE", "UNCERTAIN"]
    tags: Annotated[tuple[ShortText, ...], Field(min_length=1)]
    baseline_key: ShortText | None
    selected_vendor_id: UUID
    sources: Annotated[tuple[SourceDocument, ...], Field(min_length=1, max_length=16)]
    gold_evidence: PaymentRequestEvidence
    non_destination_spans: tuple[NonDestinationSpan, ...] = ()
    normalized_gold_requested_identity: NormalizedPaymentIdentity | None
    ground_truth: BenchmarkTruth
    after_gold_source_review: BenchmarkExpectation
    without_source_review: BenchmarkExpectation

    @model_validator(mode="after")
    def no_prediction_or_invented_observation(self) -> "BenchmarkCase":
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("case tags must be unique")
        if self.gold_evidence.extraction.method != "FIXTURE":
            raise ValueError("gold observations must be explicitly fixture attributed")
        if self.gold_evidence.extraction.failure_code is not None:
            raise ValueError("source ambiguity/unreadability is not a fabricated provider failure")
        if self.without_source_review.state != "UNCERTAIN" or "REVIEW_REQUIRED" not in (
            self.without_source_review.reason_codes
        ):
            raise ValueError("unreviewed successful extraction requires review")
        if self.after_gold_source_review.state != "UNCERTAIN":
            truth = self.ground_truth
            if not truth.phase1_comparable or self.normalized_gold_requested_identity is None:
                raise ValueError("decisive expectations require a supported complete identity")
            expected_relation = (
                "UNCHANGED" if self.after_gold_source_review.state == "UNCHANGED" else "CHANGED"
            )
            if truth.destination_relation != expected_relation:
                raise ValueError("expected state must agree with independent destination truth")
        elif self.ground_truth.phase1_comparable:
            raise ValueError("complete gold comparable inputs cannot have an uncertain expectation")
        return self


class BenchmarkCorpus(Contract):
    schema_version: Literal["payproof-benchmark-design-v1"]
    dataset_id: Literal["payproof-phase1-diagnostic-30-v1"]
    evaluation_status: Literal["NOT_RUN"]
    independent_label_review: Literal["PENDING"]
    split: Literal["PUBLIC_DIAGNOSTIC_NOT_HELD_OUT"]
    rule_version: Literal["iban-gb-de-v1"]
    gold_review_protocol: Literal["SIMULATED_GOLD_SOURCE_REVIEW"]
    baselines: Annotated[tuple[BenchmarkBaseline, ...], Field(min_length=1)]
    cases: Annotated[tuple[BenchmarkCase, ...], Field(min_length=20, max_length=30)]

    @model_validator(mode="after")
    def references_and_grounding(self) -> "BenchmarkCorpus":
        by_key = {baseline.key: baseline.record for baseline in self.baselines}
        if len(by_key) != len(self.baselines):
            raise ValueError("baseline keys must be unique")
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("case IDs must be unique")
        for case in self.cases:
            baseline = None
            if case.baseline_key is not None:
                if case.baseline_key not in by_key:
                    raise ValueError("case references an unknown trusted baseline")
                baseline = by_key[case.baseline_key]
                if baseline.vendor_id != case.selected_vendor_id:
                    raise ValueError("case vendor must bind to the selected baseline")
            elif (
                case.ground_truth.boundary != "MISSING_TRUSTED_HISTORY"
                or "BASELINE_UNAVAILABLE" not in case.after_gold_source_review.reason_codes
            ):
                raise ValueError("missing history must not invent a trusted record")
            # Validate source quotes/digests, dates, and normalized gold annotations.
            # This checks data contracts only; it does not execute comparison rules.
            review = SourceReview(
                review_id=uuid5(NAMESPACE_URL, f"benchmark-contract-review:{case.case_id}"),
                request_id=case.gold_evidence.request_id,
                attempt_id=case.gold_evidence.extraction.attempt_id,
                operator_id="synthetic-gold-contract-validation",
                reviewed_at=case.gold_evidence.extraction.extracted_at,
                destination_instructions_checked=True,
                reviewed_evidence_ids=tuple(s.evidence_id for s in case.gold_evidence.spans()),
                payment_identity=case.normalized_gold_requested_identity,
            )
            CaseContract(
                sources=case.sources,
                evidence=case.gold_evidence,
                baseline=baseline,
                review=review,
            )
            sources = {source.source_id: source for source in case.sources}
            for span in case.non_destination_spans:
                source = sources.get(span.source_id)
                if source is None or (
                    source.text[span.location.char_start : span.location.char_end]
                    != span.exact_excerpt
                    or span.raw_value not in span.exact_excerpt
                    or span.location.page_number != source.page_number
                ):
                    raise ValueError("non-destination annotations must have exact source support")
            state = case.after_gold_source_review.state
            if state != "UNCERTAIN":
                assert baseline is not None and review.payment_identity is not None
                equal = (
                    baseline.payment_identity.account_identifier
                    == review.payment_identity.account_identifier
                )
                if (state == "UNCHANGED") != equal:
                    raise ValueError("decisive label contradicts the frozen full identities")
        return self
