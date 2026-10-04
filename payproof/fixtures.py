"""Load bundled synthetic fixtures and validate references and source grounding."""

from dataclasses import dataclass
from importlib.resources import files
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from payproof.schemas import (
    CaseContract,
    ComparisonState,
    Contract,
    PaymentRequestEvidence,
    ReasonCode,
    ShortText,
    SourceDocument,
    TrustedVendorRecord,
)
from payproof.validation import parse_contract


class RequestFixture(Contract):
    fixture_id: ShortText
    dataset: Literal["SYNTHETIC_DEVELOPMENT"]
    description: ShortText
    vendor_id: UUID
    baseline_revision_id: UUID
    source: SourceDocument
    evidence: PaymentRequestEvidence
    expected_state_after_review: ComparisonState
    expected_reason_codes: tuple[ReasonCode, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def fixture_attribution(self) -> "RequestFixture":
        if self.evidence.extraction.method != "FIXTURE":
            raise ValueError("bundled request labels must be explicitly fixture-attributed")
        return self


@dataclass(frozen=True)
class FixtureCorpus:
    vendors: tuple[TrustedVendorRecord, ...]
    requests: tuple[RequestFixture, ...]


def load_corpus() -> FixtureCorpus:
    root = files("payproof").joinpath("fixtures")
    vendors = tuple(
        parse_contract(TrustedVendorRecord, path.read_bytes())
        for path in sorted(root.joinpath("trusted_vendors").iterdir(), key=lambda p: p.name)
        if path.name.endswith(".json")
    )
    requests = tuple(
        parse_contract(RequestFixture, path.read_bytes())
        for path in sorted(root.joinpath("requests").iterdir(), key=lambda p: p.name)
        if path.name.endswith(".json")
    )
    if not vendors or not requests:
        raise ValueError("synthetic fixture corpus must not be empty")
    by_revision = {(vendor.vendor_id, vendor.revision_id): vendor for vendor in vendors}
    if len(by_revision) != len(vendors):
        raise ValueError("fixture vendor revisions must be unique")
    if len({request.fixture_id for request in requests}) != len(requests):
        raise ValueError("request fixture IDs must be unique")
    for request in requests:
        baseline = by_revision.get((request.vendor_id, request.baseline_revision_id))
        if baseline is None or baseline.provenance.source_kind != "SYNTHETIC_FIXTURE":
            raise ValueError("request must reference a synthetic trusted vendor revision")
        CaseContract(sources=(request.source,), evidence=request.evidence, baseline=baseline)
    return FixtureCorpus(vendors=vendors, requests=requests)
