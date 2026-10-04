"""Canonical v1 contracts and invariant validation, without application services.

JSON inputs must use model_validate_json(); Python inputs are strictly typed.
CaseContract is the cross-record validation boundary, not an AI output schema.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from payproof.normalization import canonical_iban


def nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


def utc_timestamp(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be timezone-aware UTC")
    return value


Text = Annotated[str, Field(min_length=1, max_length=2000), AfterValidator(nonblank)]
ShortText = Annotated[str, Field(min_length=1, max_length=256), AfterValidator(nonblank)]
UTCDateTime = Annotated[datetime, AfterValidator(utc_timestamp)]
Currency = Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")]
Email = Annotated[
    str,
    Field(
        max_length=254,
        pattern=r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$",
    ),
]
Domain = Annotated[
    str, Field(max_length=253, pattern=r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
]
SourceKind = Literal["EMAIL", "INVOICE", "VENDOR_NOTICE", "PLAIN_TEXT"]
EvidenceField = Literal[
    "vendor_name",
    "sender_email",
    "reply_to",
    "invoice_number",
    "amount",
    "currency",
    "bank_name",
    "account_identifier",
    "routing_identifier",
    "destination_scheme",
    "claims_details_changed",
    "stated_reason_for_change",
]
ExtractionStatus = Literal["FOUND", "MISSING", "AMBIGUOUS", "UNREADABLE", "UNSUPPORTED"]
ComparisonState = Literal["UNCHANGED", "VERIFY", "UNCERTAIN"]
ReasonCode = Literal[
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
    "DESTINATION_MATCH",
    "DESTINATION_CHANGED",
]


class Contract(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, validate_default=True)


class SourceDocument(Contract):
    source_id: UUID
    kind: SourceKind
    text: Annotated[str, Field(min_length=1, max_length=20_000), AfterValidator(nonblank)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    captured_at: UTCDateTime
    captured_by: ShortText
    label: ShortText | None = None
    page_number: Annotated[int, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def digest_matches(self) -> SourceDocument:
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.sha256:
            raise ValueError("source digest does not match exact UTF-8 text")
        return self


class SourceLocation(Contract):
    char_start: Annotated[int, Field(ge=0)]
    char_end: Annotated[int, Field(gt=0)]
    page_number: Annotated[int, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def ordered_offsets(self) -> SourceLocation:
        if self.char_end <= self.char_start:
            raise ValueError("evidence interval must be nonempty and ordered")
        return self


class EvidenceSpan(Contract):
    evidence_id: UUID
    source_id: UUID
    field: EvidenceField
    extracted_value: Text
    exact_excerpt: Annotated[str, Field(min_length=1, max_length=20_000)]
    location: SourceLocation
    extraction_status: Literal["FOUND", "AMBIGUOUS"]

    @model_validator(mode="after")
    def value_is_grounded(self) -> EvidenceSpan:
        if self.extracted_value not in self.exact_excerpt:
            raise ValueError("raw extracted value must occur verbatim in excerpt")
        if len(self.exact_excerpt) != self.location.char_end - self.location.char_start:
            raise ValueError("excerpt length must match character interval")
        return self


ValueT = TypeVar("ValueT")


class ExtractedCandidate(Contract, Generic[ValueT]):
    value: ValueT
    evidence: EvidenceSpan

    @model_validator(mode="after")
    def raw_string_matches(self) -> ExtractedCandidate[ValueT]:
        if isinstance(self.value, str) and self.value != self.evidence.extracted_value:
            raise ValueError("string candidate must preserve the verbatim extracted value")
        return self


class ExtractedField(Contract, Generic[ValueT]):
    status: ExtractionStatus
    candidates: tuple[ExtractedCandidate[ValueT], ...]

    @model_validator(mode="after")
    def cardinality_and_status(self) -> ExtractedField[ValueT]:
        count = len(self.candidates)
        if self.status == "FOUND" and count != 1:
            raise ValueError("FOUND requires exactly one candidate")
        if self.status == "AMBIGUOUS" and count < 2:
            raise ValueError("AMBIGUOUS requires at least two candidates")
        if self.status in ("MISSING", "UNREADABLE", "UNSUPPORTED") and count:
            raise ValueError("non-extracted fields must not invent values or evidence")
        if any(c.evidence.extraction_status != self.status for c in self.candidates):
            raise ValueError("candidate evidence status must agree with field status")
        return self


class ExtractionMetadata(Contract):
    attempt_id: UUID
    method: Literal["AI", "MANUAL", "FIXTURE", "NOT_ATTEMPTED"]
    extracted_at: UTCDateTime
    schema_version: Literal["1"]
    prompt_version: ShortText | None = None
    provider: ShortText | None = None
    model: ShortText | None = None
    operator_id: ShortText | None = None
    failure_code: (
        Literal[
            "TIMEOUT",
            "PROVIDER_UNAVAILABLE",
            "INVALID_RESPONSE",
            "EVIDENCE_INVALID",
            "NOT_CONFIGURED",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def attribution(self) -> ExtractionMetadata:
        if self.failure_code == "NOT_CONFIGURED" and self.method != "NOT_ATTEMPTED":
            raise ValueError("unconfigured extractor must use NOT_ATTEMPTED")
        if self.method == "AI":
            if not (self.provider and self.model and self.prompt_version):
                raise ValueError("AI extraction requires provider, model, and prompt version")
            if self.operator_id is not None:
                raise ValueError("AI output cannot assert a human operator")
        elif self.method == "NOT_ATTEMPTED":
            if self.failure_code != "NOT_CONFIGURED" or any(
                (self.provider, self.model, self.prompt_version, self.operator_id)
            ):
                raise ValueError(
                    "unconfigured extraction must not invent provider or human attribution"
                )
        elif not self.operator_id or any((self.provider, self.model, self.prompt_version)):
            raise ValueError("manual/fixture extraction requires operator and no AI attribution")
        return self


class ExtractionPayload(Contract):
    """Provider-facing schema: only extracted fields, no server attribution/IDs."""

    vendor_name: ExtractedField[Text]
    sender_email: ExtractedField[Text]
    reply_to: ExtractedField[Text]
    invoice_number: ExtractedField[Text]
    amount: ExtractedField[Text]
    currency: ExtractedField[Text]
    bank_name: ExtractedField[Text]
    account_identifier: ExtractedField[Text]
    routing_identifier: ExtractedField[Text]
    destination_scheme: ExtractedField[Text]
    claims_details_changed: ExtractedField[bool]
    stated_reason_for_change: ExtractedField[Text]


class PaymentRequestEvidence(ExtractionPayload):
    """Extraction plus server attribution; no decision, review, or trust fields."""

    request_id: UUID
    source_ids: Annotated[tuple[UUID, ...], Field(min_length=1)]
    extraction: ExtractionMetadata

    @model_validator(mode="after")
    def references_and_fields(self) -> PaymentRequestEvidence:
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source IDs must be unique")
        seen: set[UUID] = set()
        for name in EVIDENCE_FIELDS:
            if self.extraction.failure_code and getattr(self, name).status != "UNREADABLE":
                raise ValueError("failed extraction must contain only UNREADABLE fields")
            for candidate in getattr(self, name).candidates:
                span = candidate.evidence
                if span.field != name or span.source_id not in self.source_ids:
                    raise ValueError("evidence must reference its field and a declared source")
                if span.evidence_id in seen:
                    raise ValueError("evidence IDs must be unique within a request")
                seen.add(span.evidence_id)
        return self

    def spans(self) -> tuple[EvidenceSpan, ...]:
        return tuple(c.evidence for name in EVIDENCE_FIELDS for c in getattr(self, name).candidates)


EVIDENCE_FIELDS = (
    "vendor_name",
    "sender_email",
    "reply_to",
    "invoice_number",
    "amount",
    "currency",
    "bank_name",
    "account_identifier",
    "routing_identifier",
    "destination_scheme",
    "claims_details_changed",
    "stated_reason_for_change",
)


class NormalizedPaymentIdentity(Contract):
    normalization_version: Literal["iban-gb-de-v1"]
    scheme: Literal["IBAN"]
    raw_account_identifier: ShortText
    account_identifier: ShortText
    routing_identifier: None = None

    @model_validator(mode="after")
    def canonical_matches_raw(self) -> NormalizedPaymentIdentity:
        if canonical_iban(self.raw_account_identifier) != self.account_identifier:
            raise ValueError(
                "canonical account must equal deterministic normalization of raw account"
            )
        return self


class TrustProvenance(Contract):
    source_kind: Literal[
        "PRIOR_VENDOR_RECORD", "ONBOARDING_RECORD", "INDEPENDENT_CALLBACK", "SYNTHETIC_FIXTURE"
    ]
    source_reference: Text
    description: Text
    recorded_by: ShortText
    recorded_at: UTCDateTime


class TrustedCallbackContact(Contract):
    contact_id: UUID
    revision_id: UUID
    method: Literal["PHONE", "KNOWN_PORTAL", "IN_PERSON"]
    value: ShortText
    provenance: TrustProvenance
    last_verified_at: UTCDateTime

    @model_validator(mode="after")
    def verified_after_origin(self) -> TrustedCallbackContact:
        if self.last_verified_at < self.provenance.recorded_at:
            raise ValueError("contact verification cannot predate its provenance")
        return self


class TrustedVendorRecord(Contract):
    vendor_id: UUID
    revision_id: UUID
    canonical_vendor_name: ShortText
    trusted_email: Email | None = None
    trusted_domain: Domain | None = None
    callback_contact: TrustedCallbackContact
    bank_name: ShortText | None = None
    payment_identity: NormalizedPaymentIdentity
    routing_identifier: ShortText | None = None
    currency: Currency | None = None
    provenance: TrustProvenance
    last_verified_at: UTCDateTime

    @model_validator(mode="after")
    def trustworthy_snapshot(self) -> TrustedVendorRecord:
        if self.last_verified_at < self.provenance.recorded_at:
            raise ValueError("baseline verification cannot predate provenance")
        if self.callback_contact.last_verified_at > self.last_verified_at:
            raise ValueError("baseline snapshot must include an already verified contact")
        if self.trusted_email and self.trusted_domain:
            if self.trusted_email.rsplit("@", 1)[1].lower() != self.trusted_domain:
                raise ValueError("trusted email must belong to the declared trusted domain")
        return self


class SourceReview(Contract):
    review_id: UUID
    request_id: UUID
    attempt_id: UUID
    operator_id: ShortText
    reviewed_at: UTCDateTime
    destination_instructions_checked: Literal[True]
    reviewed_evidence_ids: tuple[UUID, ...]
    payment_identity: NormalizedPaymentIdentity | None

    @field_validator("destination_instructions_checked", mode="before")
    @classmethod
    def explicit_review(cls, value: object) -> object:
        if value is not True:
            raise ValueError("source review requires explicit boolean true")
        return value


class FieldDifference(Contract):
    field: EvidenceField
    baseline_value: Text | None
    requested_value: Text | None
    status: Literal["MATCH", "CHANGED", "UNKNOWN"]
    evidence_ids: tuple[UUID, ...]

    @model_validator(mode="after")
    def values_match_status(self) -> FieldDifference:
        if self.baseline_value is None or self.requested_value is None:
            if self.status != "UNKNOWN":
                raise ValueError("missing values require UNKNOWN difference")
        elif self.status == "UNKNOWN":
            raise ValueError("UNKNOWN difference requires a missing value")
        elif (self.baseline_value == self.requested_value) != (self.status == "MATCH"):
            raise ValueError("difference status must agree with its canonical/display values")
        return self


class MissingInformation(Contract):
    field: EvidenceField
    side: Literal["BASELINE", "REQUEST"]
    explanation: Text


class Contradiction(Contract):
    field: EvidenceField
    explanation: Text
    evidence_ids: Annotated[tuple[UUID, ...], Field(min_length=2)]

    @model_validator(mode="after")
    def distinct_evidence(self) -> Contradiction:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("contradiction must reference distinct evidence")
        return self


class ComparisonResult(Contract):
    comparison_id: UUID
    request_id: UUID
    vendor_id: UUID
    baseline_revision_id: UUID | None
    review_id: UUID | None
    rule_version: Literal["iban-gb-de-v1"]
    compared_at: UTCDateTime
    state: ComparisonState
    baseline_identity: NormalizedPaymentIdentity | None
    requested_identity: NormalizedPaymentIdentity | None
    differences: tuple[FieldDifference, ...]
    missing_information: tuple[MissingInformation, ...]
    contradictions: tuple[Contradiction, ...]
    evidence_ids: tuple[UUID, ...]
    reason_codes: Annotated[tuple[ReasonCode, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def result_invariants(self) -> ComparisonResult:
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason codes must be unique")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("comparison evidence IDs must be unique")
        if len({d.field for d in self.differences}) != len(self.differences):
            raise ValueError("only one difference per field is allowed")
        linked = tuple(e for d in self.differences for e in d.evidence_ids) + tuple(
            e for c in self.contradictions for e in c.evidence_ids
        )
        if not set(linked).issubset(self.evidence_ids):
            raise ValueError("difference/contradiction references must be declared evidence")
        if self.state == "UNCERTAIN":
            if any(r in ("DESTINATION_MATCH", "DESTINATION_CHANGED") for r in self.reason_codes):
                raise ValueError("UNCERTAIN cannot assert a decisive reason")
            return self
        if not (
            self.baseline_revision_id
            and self.review_id
            and self.baseline_identity
            and self.requested_identity
        ):
            raise ValueError(
                "decisive comparisons require baseline, review, and both valid identities"
            )
        destination_fields = ("account_identifier", "routing_identifier", "destination_scheme")
        if any(c.field in destination_fields for c in self.contradictions) or any(
            m.field in destination_fields for m in self.missing_information
        ):
            raise ValueError("decisive comparison cannot have unresolved destination information")
        equal = (
            self.baseline_identity.account_identifier == self.requested_identity.account_identifier
        )
        expected = "UNCHANGED" if equal else "VERIFY"
        reason = "DESTINATION_MATCH" if equal else "DESTINATION_CHANGED"
        if self.state != expected or self.reason_codes != (reason,):
            raise ValueError("state and reason must agree with exact destination equality")
        accounts = [d for d in self.differences if d.field == "account_identifier"]
        if len(accounts) != 1:
            raise ValueError("decisive result requires one account difference with evidence")
        diff = accounts[0]
        if (
            not diff.evidence_ids
            or diff.baseline_value != self.baseline_identity.account_identifier
            or diff.requested_value != self.requested_identity.account_identifier
        ):
            raise ValueError(
                "account difference must match identity snapshots and reference evidence"
            )
        return self


class HumanVerificationRecord(Contract):
    """A human's independent confirmation of destination instructions, not ownership."""

    verification_id: UUID
    comparison_id: UUID
    vendor_id: UUID
    baseline_revision_id: UUID
    trusted_contact_id: UUID
    trusted_contact_revision_id: UUID
    callback_method: Literal["PHONE", "KNOWN_PORTAL", "IN_PERSON"]
    trusted_callback_value: ShortText
    trusted_source: TrustProvenance
    checked_identity: NormalizedPaymentIdentity
    what_was_checked: Literal["EXACT_PAYMENT_DESTINATION_INSTRUCTIONS"]
    independently_reached_person: ShortText
    operator_id: ShortText
    human_confirmed: Literal[True]
    confirmed_at: UTCDateTime
    notes: Text | None = None

    @field_validator("human_confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("human confirmation requires explicit boolean true")
        return value


class CaseContract(Contract):
    """Validate source grounding and cross-record bindings before accepting snapshots.

    Storage/application must additionally check current revisions atomically and
    authenticate the operator; a valid object alone confers no authority.
    """

    sources: Annotated[tuple[SourceDocument, ...], Field(min_length=1)]
    evidence: PaymentRequestEvidence
    baseline: TrustedVendorRecord | None
    review: SourceReview | None = None
    comparison: ComparisonResult | None = None
    verification: HumanVerificationRecord | None = None

    @model_validator(mode="after")
    def cross_record_invariants(self) -> CaseContract:
        sources = {s.source_id: s for s in self.sources}
        if sum(len(s.text) for s in self.sources) > 20_000:
            raise ValueError("total request source text exceeds Phase-1 limit")
        if len(sources) != len(self.sources) or set(sources) != set(self.evidence.source_ids):
            raise ValueError("source snapshots must uniquely match declared sources")
        spans = {s.evidence_id: s for s in self.evidence.spans()}
        for span in spans.values():
            source = sources[span.source_id]
            if source.text[span.location.char_start : span.location.char_end] != span.exact_excerpt:
                raise ValueError("evidence excerpt does not match immutable source offsets")
            if span.location.page_number != source.page_number:
                raise ValueError("page location must come from source metadata")
        if any(s.captured_at > self.evidence.extraction.extracted_at for s in self.sources):
            raise ValueError("extraction cannot predate source capture")
        if self.baseline and self.baseline.last_verified_at >= min(
            s.captured_at for s in self.sources
        ):
            raise ValueError("trusted baseline must predate the request's capture")
        review = self.review
        if review:
            if (
                review.request_id != self.evidence.request_id
                or review.attempt_id != self.evidence.extraction.attempt_id
            ):
                raise ValueError("review must bind to this request and extraction attempt")
            if review.reviewed_at < self.evidence.extraction.extracted_at:
                raise ValueError("review cannot predate extraction")
            if len(set(review.reviewed_evidence_ids)) != len(
                review.reviewed_evidence_ids
            ) or not set(review.reviewed_evidence_ids).issubset(spans):
                raise ValueError("review must reference unique existing evidence")
            if review.payment_identity:
                accounts = self.evidence.account_identifier
                if accounts.status != "FOUND":
                    raise ValueError("reviewed identity requires an unambiguous account")
                candidate = accounts.candidates[0]
                if (
                    candidate.evidence.evidence_id not in review.reviewed_evidence_ids
                    or candidate.value != review.payment_identity.raw_account_identifier
                ):
                    raise ValueError("reviewed identity must bind to the exact account evidence")
        result = self.comparison
        if result:
            if result.request_id != self.evidence.request_id or not set(
                result.evidence_ids
            ).issubset(spans):
                raise ValueError("comparison must bind to this request and existing evidence")
            for difference in result.differences:
                if any(spans[e].field != difference.field for e in difference.evidence_ids):
                    raise ValueError("difference evidence must belong to the compared field")
                if difference.requested_value is not None:
                    if not difference.evidence_ids:
                        raise ValueError("requested difference values require source evidence")
                    if difference.field != "account_identifier" and not any(
                        spans[e].extracted_value == difference.requested_value
                        for e in difference.evidence_ids
                    ):
                        raise ValueError(
                            "contextual requested values must preserve raw extracted evidence"
                        )
            for contradiction in result.contradictions:
                if any(spans[e].field != contradiction.field for e in contradiction.evidence_ids):
                    raise ValueError("contradiction evidence must belong to its field")
            if result.compared_at < self.evidence.extraction.extracted_at:
                raise ValueError("comparison cannot predate extraction")
            if self.baseline:
                if (
                    result.vendor_id != self.baseline.vendor_id
                    or result.baseline_revision_id != self.baseline.revision_id
                    or result.baseline_identity != self.baseline.payment_identity
                ):
                    raise ValueError("comparison must bind to exact baseline snapshot")
            elif (
                result.baseline_revision_id is not None
                or result.baseline_identity is not None
                or result.state != "UNCERTAIN"
            ):
                raise ValueError("missing baseline permits only UNCERTAIN without baseline claims")
            if review:
                if (
                    result.review_id != review.review_id
                    or result.requested_identity != review.payment_identity
                    or result.compared_at < review.reviewed_at
                ):
                    raise ValueError("comparison must bind to the exact prior review")
            elif (
                result.review_id is not None
                or result.requested_identity is not None
                or result.state != "UNCERTAIN"
            ):
                raise ValueError("missing review permits only UNCERTAIN without reviewed identity")
            if result.state != "UNCERTAIN":
                assert self.baseline is not None  # Checked against result state above.
                if (
                    self.evidence.routing_identifier.status != "MISSING"
                    or self.evidence.destination_scheme.status not in ("FOUND", "MISSING")
                    or self.baseline.routing_identifier is not None
                ):
                    raise ValueError(
                        "separate routing or unresolved scheme is unsupported in Phase 1"
                    )
                if (
                    self.evidence.destination_scheme.status == "FOUND"
                    and self.evidence.destination_scheme.candidates[0].value.upper() != "IBAN"
                ):
                    raise ValueError("only IBAN is supported in Phase 1")
                account_span = self.evidence.account_identifier.candidates[0].evidence.evidence_id
                account_diff = next(
                    d for d in result.differences if d.field == "account_identifier"
                )
                if account_span not in account_diff.evidence_ids:
                    raise ValueError("account difference must cite the reviewed account span")
            else:
                if self.baseline is None and not set(result.reason_codes).intersection(
                    ("BASELINE_UNAVAILABLE", "BASELINE_INVALID")
                ):
                    raise ValueError("missing baseline requires a baseline reason")
                if review is None and not set(result.reason_codes).intersection(
                    ("REVIEW_REQUIRED", "EXTRACTION_FAILED", "EVIDENCE_INVALID")
                ):
                    raise ValueError("missing review requires an extraction/evidence/review reason")
                if self.evidence.extraction.failure_code:
                    expected = (
                        "EVIDENCE_INVALID"
                        if self.evidence.extraction.failure_code == "EVIDENCE_INVALID"
                        else "EXTRACTION_FAILED"
                    )
                    if expected not in result.reason_codes:
                        raise ValueError("failed extraction requires the corresponding reason")
        verification = self.verification
        if verification:
            if not result or result.state == "UNCERTAIN" or not self.baseline:
                raise ValueError("verification requires a decisive comparison and baseline")
            contact = self.baseline.callback_contact
            if (
                verification.comparison_id != result.comparison_id
                or verification.vendor_id != result.vendor_id
                or verification.baseline_revision_id != result.baseline_revision_id
            ):
                raise ValueError("verification must bind to the exact comparison and baseline")
            if verification.checked_identity != result.requested_identity:
                raise ValueError("verification must check the exact requested destination snapshot")
            if (
                verification.trusted_contact_id,
                verification.trusted_contact_revision_id,
                verification.callback_method,
                verification.trusted_callback_value,
                verification.trusted_source,
            ) != (
                contact.contact_id,
                contact.revision_id,
                contact.method,
                contact.value,
                contact.provenance,
            ):
                raise ValueError("verification must use the previously trusted contact snapshot")
            if verification.confirmed_at < result.compared_at:
                raise ValueError("verification cannot predate comparison")
        return self
