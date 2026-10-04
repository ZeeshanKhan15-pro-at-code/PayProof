"""Synthetic contract examples; no live vendor or financial data."""

import hashlib
from copy import deepcopy

from payproof.schemas import EVIDENCE_FIELDS


GB_IBAN = "GB82WEST12345698765432"
DE_IBAN = "DE89370400440532013000"


def uid(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012d}"


def identity(raw: str, canonical: str | None = None) -> dict:
    return {
        "normalization_version": "iban-gb-de-v1", "scheme": "IBAN",
        "raw_account_identifier": raw,
        "account_identifier": canonical if canonical is not None else raw,
        "routing_identifier": None,
    }


def provenance() -> dict:
    return {
        "source_kind": "SYNTHETIC_FIXTURE",
        "source_reference": "synthetic-onboarding-001",
        "description": "Synthetic prior vendor record; no real contact or account.",
        "recorded_by": "demo-operator", "recorded_at": "2026-10-01T08:00:00Z",
    }


def field(value: str | bool, raw: str, source_text: str, name: str, evidence_number: int = 9) -> dict:
    start = source_text.index(raw)
    return {
        "status": "FOUND", "candidates": [{
            "value": value, "evidence": {
                "evidence_id": uid(evidence_number), "source_id": uid(1), "field": name,
                "extracted_value": raw, "exact_excerpt": raw,
                "location": {"char_start": start, "char_end": start + len(raw), "page_number": None},
                "extraction_status": "FOUND",
            },
        }],
    }


def valid_case(state: str = "VERIFY", verified: bool = False) -> dict:
    requested = DE_IBAN if state == "VERIFY" else GB_IBAN
    source_text = f"Please pay invoice INV-001 to IBAN {requested}."
    if state == "UNCERTAIN":
        source_text = "Please pay invoice INV-001. Payment details to follow."
    evidence = {name: {"status": "MISSING", "candidates": []} for name in EVIDENCE_FIELDS}
    evidence.update({
        "request_id": uid(2), "source_ids": [uid(1)],
        "extraction": {
            "attempt_id": uid(3), "method": "AI", "extracted_at": "2026-10-04T08:01:00Z",
            "schema_version": "1", "prompt_version": "extract-v1", "provider": "test-provider",
            "model": "test-model", "operator_id": None, "failure_code": None,
        },
    })
    if state != "UNCERTAIN":
        evidence["account_identifier"] = field(requested, requested, source_text, "account_identifier")
    baseline = {
        "vendor_id": uid(4), "revision_id": uid(5), "canonical_vendor_name": "Synthetic Vendor",
        "trusted_email": "accounts@vendor.example", "trusted_domain": "vendor.example",
        "callback_contact": {
            "contact_id": uid(6), "revision_id": uid(7), "method": "PHONE",
            "value": "+1-202-555-0100", "provenance": provenance(),
            "last_verified_at": "2026-10-02T08:00:00Z",
        },
        "bank_name": "Synthetic Bank", "payment_identity": identity(GB_IBAN),
        "routing_identifier": None, "currency": "GBP", "provenance": provenance(),
        "last_verified_at": "2026-10-03T08:00:00Z",
    }
    review = {
        "review_id": uid(8), "request_id": uid(2), "attempt_id": uid(3),
        "operator_id": "demo-operator", "reviewed_at": "2026-10-04T08:02:00Z",
        "destination_instructions_checked": True,
        "reviewed_evidence_ids": [uid(9)] if state != "UNCERTAIN" else [],
        "payment_identity": identity(requested) if state != "UNCERTAIN" else None,
    }
    comparison = {
        "comparison_id": uid(10), "request_id": uid(2), "vendor_id": uid(4),
        "baseline_revision_id": uid(5), "review_id": uid(8), "rule_version": "iban-gb-de-v1",
        "compared_at": "2026-10-04T08:03:00Z", "state": state,
        "baseline_identity": identity(GB_IBAN), "requested_identity": review["payment_identity"],
        "differences": [{
            "field": "account_identifier", "baseline_value": GB_IBAN,
            "requested_value": requested if state != "UNCERTAIN" else None,
            "status": {"VERIFY": "CHANGED", "UNCHANGED": "MATCH", "UNCERTAIN": "UNKNOWN"}[state],
            "evidence_ids": [uid(9)] if state != "UNCERTAIN" else [],
        }],
        "missing_information": [{"field": "account_identifier", "side": "REQUEST", "explanation": "Not present in source."}] if state == "UNCERTAIN" else [],
        "contradictions": [], "evidence_ids": [uid(9)] if state != "UNCERTAIN" else [],
        "reason_codes": [{"VERIFY": "DESTINATION_CHANGED", "UNCHANGED": "DESTINATION_MATCH", "UNCERTAIN": "DESTINATION_MISSING"}[state]],
    }
    verification = None
    if verified:
        verification = {
            "verification_id": uid(11), "comparison_id": uid(10), "vendor_id": uid(4),
            "baseline_revision_id": uid(5), "trusted_contact_id": uid(6), "trusted_contact_revision_id": uid(7),
            "callback_method": "PHONE", "trusted_callback_value": "+1-202-555-0100",
            "trusted_source": provenance(), "checked_identity": identity(requested),
            "what_was_checked": "EXACT_PAYMENT_DESTINATION_INSTRUCTIONS",
            "independently_reached_person": "Synthetic vendor contact (simulated)",
            "operator_id": "demo-operator", "human_confirmed": True,
            "confirmed_at": "2026-10-04T08:04:00Z", "notes": "Synthetic verification demonstration only.",
        }
    return deepcopy({
        "sources": [{
            "source_id": uid(1), "kind": "PLAIN_TEXT", "text": source_text,
            "sha256": hashlib.sha256(source_text.encode()).hexdigest(),
            "captured_at": "2026-10-04T08:00:00Z", "captured_by": "demo-operator",
            "label": "Synthetic invoice excerpt", "page_number": None,
        }],
        "evidence": evidence, "baseline": baseline, "review": review,
        "comparison": comparison, "verification": verification,
    })
