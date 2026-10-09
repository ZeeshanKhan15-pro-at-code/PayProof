"""Explicit optional synthetic replay; never invoked as live extraction fallback."""

import json
from importlib.resources import files
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from payproof.demo_proof import DemoCase
from payproof.schemas import CaseContract, Contract, TrustedVendorRecord
from payproof.validation import parse_contract
from payproof.workflow_contracts import CaseInputs


class ExampleCatalog(Contract):
    dataset: Literal["SYNTHETIC_PUBLIC_EXAMPLES_V1"]
    vendor: TrustedVendorRecord
    cases: tuple[DemoCase, ...] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def synthetic_grounded_inputs(self) -> "ExampleCatalog":
        if len({c.case_id for c in self.cases}) != len(self.cases):
            raise ValueError("example IDs must be unique")
        if self.vendor.provenance.source_kind != "SYNTHETIC_FIXTURE":
            raise ValueError("example baseline must be synthetic")
        for item in self.cases:
            CaseContract(**item.inputs.model_dump(), baseline=self.vendor)
            if item.inputs.evidence.extraction.method != "FIXTURE":
                raise ValueError("synthetic replay must not impersonate live extraction")
            if any(
                not s.label or "SYNTHETIC DEMONSTRATION" not in s.label for s in item.inputs.sources
            ):
                raise ValueError("every example source must be explicitly labeled synthetic")
        return self


def load_examples() -> ExampleCatalog:
    return parse_contract(
        ExampleCatalog,
        files("payproof").joinpath("fixtures/demo_proof/public_examples.json").read_bytes(),
    )


def instantiate_example(
    catalog: ExampleCatalog, item: DemoCase, submission_id: UUID
) -> tuple[TrustedVendorRecord, CaseInputs]:
    """Fresh replay namespace keeps user edits/history out of a new demonstration.

    Submission IDs identify idempotent creation only; all facts are server-owned
    catalog data. No review, comparison or human verification is preassigned.
    """

    def identifier(kind: str, original: str = "") -> str:
        return str(uuid5(NAMESPACE_URL, f"synthetic-example:{submission_id}:{kind}:{original}"))

    vendor = catalog.vendor.model_dump(mode="json")
    vendor["vendor_id"] = identifier("vendor")
    vendor["revision_id"] = identifier("vendor-revision")
    vendor["callback_contact"]["contact_id"] = identifier("contact")
    vendor["callback_contact"]["revision_id"] = identifier("contact-revision")
    inputs = item.inputs.model_dump(mode="json")
    source_ids = {s["source_id"]: identifier("source", s["source_id"]) for s in inputs["sources"]}
    for source in inputs["sources"]:
        source["source_id"] = source_ids[source["source_id"]]
    evidence = inputs["evidence"]
    evidence["request_id"] = identifier("case")
    evidence["source_ids"] = [source_ids[s] for s in evidence["source_ids"]]
    evidence["extraction"]["attempt_id"] = identifier("attempt")
    for field in evidence.values():
        if isinstance(field, dict) and "candidates" in field:
            for candidate in field["candidates"]:
                span = candidate["evidence"]
                span["source_id"] = source_ids[span["source_id"]]
                span["evidence_id"] = identifier("evidence", span["evidence_id"])
    return (
        parse_contract(TrustedVendorRecord, json.dumps(vendor)),
        parse_contract(CaseInputs, json.dumps(inputs)),
    )
