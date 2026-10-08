"""Human-established baseline drafts; extraction never confers trust."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import model_validator

from payproof.cases import candidate_identity
from payproof.instruction_safety import instruction_gate
from payproof.normalization import canonical_iban
from payproof.schemas import (
    Contract,
    Currency,
    Domain,
    Email,
    NormalizedPaymentIdentity,
    ShortText,
    Text,
    TrustedCallbackContact,
    TrustedVendorRecord,
    TrustProvenance,
    UTCDateTime,
)
from payproof.workflow_contracts import CaseInputs


class BaselineDraft(Contract):
    draft_id: UUID
    vendor_id: UUID
    expected_vendor_revision_id: UUID | None = None
    operator_id: ShortText
    created_at: UTCDateTime
    submission_digest: ShortText
    name: ShortText
    bank_name: ShortText | None = None
    trusted_email: Email | None = None
    trusted_domain: Domain | None = None
    currency: Currency | None = None
    source_reference: Text
    description: Text
    prior_verified_at: UTCDateTime
    manual_account: ShortText | None = None
    inputs: CaseInputs | None = None

    @model_validator(mode="after")
    def one_input(self) -> "BaselineDraft":
        if (self.inputs is None) == (self.manual_account is None):
            raise ValueError("one baseline input method required")
        if self.prior_verified_at >= self.created_at:
            raise ValueError("baseline must have been established previously")
        return self

    def identity(self) -> NormalizedPaymentIdentity:
        if self.manual_account is not None:
            return NormalizedPaymentIdentity(
                normalization_version="iban-gb-de-v1",
                scheme="IBAN",
                raw_account_identifier=self.manual_account,
                account_identifier=canonical_iban(self.manual_account),
            )
        assert self.inputs is not None
        if self.inputs.evidence.extraction.failure_code:
            raise ValueError("failed extraction cannot establish baseline")
        gate = instruction_gate(self.inputs.sources, self.inputs.evidence)
        if gate.ambiguous or gate.incomplete:
            raise ValueError("competing or incomplete baseline instructions require resolution")
        identity = candidate_identity(self.inputs.evidence)
        if identity is None:
            raise ValueError("baseline destination is missing or ambiguous")
        if self.inputs.evidence.routing_identifier.status != "MISSING":
            raise ValueError("separate routing identifiers are outside supported baseline identity")
        schemes = self.inputs.evidence.destination_scheme
        if schemes.status not in ("MISSING", "FOUND") or any(
            c.value.strip().upper() != "IBAN" for c in schemes.candidates
        ):
            raise ValueError("unsupported baseline scheme")
        return identity


class BaselineAssertion(Contract):
    draft_id: UUID
    operator_id: ShortText
    source_reviewed: Literal[True]
    previously_trusted: Literal[True]
    contact_independently_established: Literal[True]
    contact_method: Literal["PHONE", "KNOWN_PORTAL", "IN_PERSON"]
    contact_value: ShortText

    @model_validator(mode="before")
    @classmethod
    def explicit_booleans(cls, value: object) -> object:
        if isinstance(value, dict) and any(
            value.get(k) is not True
            for k in ("source_reviewed", "previously_trusted", "contact_independently_established")
        ):
            raise ValueError("explicit human trust and contact assertions required")
        return value


def trusted_record(draft: BaselineDraft, action: BaselineAssertion) -> TrustedVendorRecord:
    if action.draft_id != draft.draft_id:
        raise ValueError("baseline assertion must reference draft")
    provenance = TrustProvenance(
        source_kind="PRIOR_VENDOR_RECORD",
        source_reference=f"baseline-draft:{draft.draft_id}; {draft.source_reference}",
        description=draft.description,
        recorded_by=action.operator_id,
        recorded_at=draft.prior_verified_at,
    )
    return TrustedVendorRecord(
        vendor_id=draft.vendor_id,
        revision_id=uuid4(),
        canonical_vendor_name=draft.name,
        bank_name=draft.bank_name,
        trusted_email=draft.trusted_email,
        trusted_domain=draft.trusted_domain,
        currency=draft.currency,
        payment_identity=draft.identity(),
        provenance=provenance,
        last_verified_at=draft.prior_verified_at,
        callback_contact=TrustedCallbackContact(
            contact_id=uuid4(),
            revision_id=uuid4(),
            method=action.contact_method,
            value=action.contact_value,
            provenance=provenance,
            last_verified_at=draft.prior_verified_at,
        ),
    )
