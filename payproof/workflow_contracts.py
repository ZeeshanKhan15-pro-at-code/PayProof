"""Local durable-workflow contracts, separate from the provider output schema."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from payproof.schemas import (
    CaseContract,
    Contract,
    HumanVerificationRecord,
    NormalizedPaymentIdentity,
    PaymentRequestEvidence,
    ShortText,
    SourceDocument,
    Text,
    TrustedCallbackContact,
    UTCDateTime,
)

VerificationOutcome = Literal["CONFIRMED", "NOT_CONFIRMED", "INCONCLUSIVE"]


class CaseInputs(Contract):
    sources: Annotated[tuple[SourceDocument, ...], Field(min_length=1, max_length=16)]
    evidence: PaymentRequestEvidence


class IndependentCheckAction(Contract):
    """Explicit human submission, with no client-controlled contact or timestamp."""

    action_id: UUID
    operator_id: ShortText
    independently_checked: Literal[True]
    what_was_checked: Literal["EXACT_PAYMENT_DESTINATION_INSTRUCTIONS"]
    outcome: VerificationOutcome
    independently_reached_person: ShortText | None = None
    notes: Text | None = None

    @field_validator("independently_checked", mode="before")
    @classmethod
    def explicit_action(cls, value: object) -> object:
        if value is not True:
            raise ValueError("independent check requires explicit boolean true")
        return value

    @model_validator(mode="after")
    def confirmation_requires_person(self) -> "IndependentCheckAction":
        if self.outcome == "CONFIRMED" and self.independently_reached_person is None:
            raise ValueError("confirmation requires the independently reached person or role")
        return self


class IndependentCheckEvent(Contract):
    event_id: UUID
    action_id: UUID
    case_id: UUID
    source_revision_id: UUID
    comparison_id: UUID
    baseline_revision_id: UUID
    trusted_contact: TrustedCallbackContact
    checked_identity: NormalizedPaymentIdentity
    what_was_checked: Literal["EXACT_PAYMENT_DESTINATION_INSTRUCTIONS"]
    outcome: VerificationOutcome
    independently_reached_person: ShortText | None
    operator_id: ShortText
    independently_checked: Literal[True]
    recorded_at: UTCDateTime
    notes: Text | None
    confirmation: HumanVerificationRecord | None

    @model_validator(mode="after")
    def confirmation_matches_event(self) -> "IndependentCheckEvent":
        if (self.outcome == "CONFIRMED") != (self.confirmation is not None):
            raise ValueError("only a confirmed outcome may have a positive confirmation")
        if self.confirmation is not None:
            record, contact = self.confirmation, self.trusted_contact
            if (
                record.comparison_id != self.comparison_id
                or record.baseline_revision_id != self.baseline_revision_id
                or record.checked_identity != self.checked_identity
                or record.confirmed_at != self.recorded_at
                or record.operator_id != self.operator_id
                or record.independently_reached_person != self.independently_reached_person
                or record.notes != self.notes
                or record.trusted_contact_id != contact.contact_id
                or record.trusted_contact_revision_id != contact.revision_id
                or record.callback_method != contact.method
                or record.trusted_callback_value != contact.value
                or record.trusted_source != contact.provenance
            ):
                raise ValueError("confirmation must bind to the exact human event")
        return self


class StoredCase(Contract):
    case_id: UUID
    revision_id: UUID
    version: Annotated[int, Field(ge=1)]
    selected_vendor_id: UUID
    recorded_at: UTCDateTime
    snapshot: CaseContract
    current_case_revision_id: UUID
    current_vendor_revision_id: UUID | None
    engine_fingerprint: ShortText | None
    current_engine_fingerprint: ShortText

    @property
    def stale(self) -> bool:
        baseline = self.snapshot.baseline
        return (
            self.revision_id != self.current_case_revision_id
            or (baseline.revision_id if baseline else None) != self.current_vendor_revision_id
            or self.engine_fingerprint is not None
            and self.engine_fingerprint != self.current_engine_fingerprint
        )

    @property
    def independent_verification_status(self) -> Literal["VERIFIED", "NOT_VERIFIED", "STALE"]:
        if self.stale:
            return "STALE"
        return "VERIFIED" if self.snapshot.verification is not None else "NOT_VERIFIED"
