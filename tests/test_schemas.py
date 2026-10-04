import hashlib
import json

import pytest
from pydantic import ValidationError

from payproof.schemas import (
    CaseContract, ComparisonResult, EvidenceSpan, ExtractionPayload, FieldDifference,
    HumanVerificationRecord, NormalizedPaymentIdentity, PaymentRequestEvidence,
    SourceDocument, TrustedVendorRecord,
)
from examples import DE_IBAN, GB_IBAN, field, identity, uid, valid_case


def parse(model, value):
    return model.model_validate_json(json.dumps(value))


def assign_path(value, path, replacement):
    for part in path[:-1]:
        value = value[part]
    value[path[-1]] = replacement


@pytest.mark.parametrize("state", ["UNCHANGED", "VERIFY", "UNCERTAIN"])
def test_complete_good_examples_round_trip(state):
    case = parse(CaseContract, valid_case(state))
    assert case.comparison.state == state
    assert case == CaseContract.model_validate_json(case.model_dump_json())
    assert case == CaseContract.model_validate(case.model_dump())


@pytest.mark.parametrize("state", ["UNCHANGED", "VERIFY"])
def test_human_record_preserves_original_comparison(state):
    case = parse(CaseContract, valid_case(state, verified=True))
    assert case.comparison.state == state
    assert case.verification.human_confirmed is True
    assert "VERIFIED" not in case.comparison.model_dump_json()
    assert "ownership" not in case.verification.model_dump()


@pytest.mark.parametrize("kind", ["EMAIL", "INVOICE", "VENDOR_NOTICE", "PLAIN_TEXT"])
def test_all_document_kinds(kind):
    data = valid_case()
    data["sources"][0]["kind"] = kind
    assert parse(CaseContract, data).sources[0].kind == kind


def test_every_extracted_field_can_be_grounded_including_boolean_claim():
    data = valid_case()
    values = {
        "vendor_name": "Synthetic Vendor", "sender_email": "sender@vendor.example",
        "reply_to": "reply@vendor.example", "invoice_number": "INV-001",
        "amount": "1,200.50", "currency": "GBP", "bank_name": "Synthetic Bank",
        "account_identifier": DE_IBAN, "routing_identifier": "FAKE-ROUTING",
        "destination_scheme": "IBAN", "claims_details_changed": "Our payment details have changed",
        "stated_reason_for_change": "We moved banks",
    }
    text = "\n".join(f"{name}: {value}" for name, value in values.items())
    data["sources"][0]["text"] = text
    data["sources"][0]["sha256"] = hashlib.sha256(text.encode()).hexdigest()
    for number, (name, raw) in enumerate(values.items(), 20):
        data["evidence"][name] = field(True if name == "claims_details_changed" else raw, raw, text, name, number)
    data["review"] = data["comparison"] = None
    case = parse(CaseContract, data)
    assert case.evidence.claims_details_changed.candidates[0].value is True
    assert case.evidence.amount.candidates[0].value == "1,200.50"


@pytest.mark.parametrize("raw,canonical", [
    (GB_IBAN, GB_IBAN), (DE_IBAN, DE_IBAN),
    ("gb82 west 1234 5698 7654 32", GB_IBAN),
    ("DE89 3704 0044 0532 0130 00", DE_IBAN),
])
def test_valid_normalized_identity(raw, canonical):
    assert parse(NormalizedPaymentIdentity, identity(raw, canonical)).account_identifier == canonical


@pytest.mark.parametrize("raw", [
    "", " ", "GB82WEST12345698765431", "GB82WEST1234569876543", "GB82WEST123456987654321",
    "DE89370400440532013001", "FR1420041010050500013M02606", "GB82-WEST12345698765432",
    "GB82\tWEST12345698765432", "GB82\nWEST12345698765432", "GB82\u00a0WEST12345698765432",
    "ＧB82WEST12345698765432", "GB82WEST1234569876543*", "GB82W3ST12345698765432",
])
def test_bad_identity_rejected(raw):
    with pytest.raises(ValidationError):
        parse(NormalizedPaymentIdentity, identity(raw))


@pytest.mark.parametrize("replacement", [DE_IBAN, GB_IBAN.lower(), "98765432"])
def test_canonical_value_cannot_be_supplied_independently(replacement):
    with pytest.raises(ValidationError):
        parse(NormalizedPaymentIdentity, identity(GB_IBAN, replacement))


@pytest.mark.parametrize("raw", ["****5432", "not an account", "FR1420041010050500013M02606"])
def test_raw_invalid_or_unsupported_account_can_be_preserved_as_evidence(raw):
    data = valid_case()
    text = f"Pay to {raw}"
    data["sources"][0]["text"] = text
    data["sources"][0]["sha256"] = hashlib.sha256(text.encode()).hexdigest()
    data["evidence"]["account_identifier"] = field(raw, raw, text, "account_identifier")
    data["review"] = data["comparison"] = None
    assert parse(CaseContract, data).evidence.account_identifier.candidates[0].value == raw


@pytest.mark.parametrize("path,replacement", [
    (("sources", 0, "sha256"), "0" * 64),
    (("sources", 0, "source_id"), "not-a-uuid"),
    (("sources", 0, "kind"), "PDF"),
    (("sources", 0, "captured_at"), "2026-10-04T08:00:00"),
    (("sources", 0, "captured_at"), "2026-10-04T13:00:00+05:00"),
    (("sources", 0, "page_number"), 0),
    (("sources", 0, "page_number"), True),
    (("sources", 0, "text"), " " * 20_001),
    (("baseline", "canonical_vendor_name"), "  "),
    (("baseline", "currency"), "usd"),
    (("baseline", "currency"), "USDT"),
    (("baseline", "trusted_email"), "not-email"),
    (("baseline", "trusted_email"), "accounts@vendor..example"),
    (("baseline", "trusted_email"), ".accounts@vendor.example"),
    (("baseline", "trusted_domain"), "https://vendor.example"),
    (("baseline", "trusted_domain"), "other.example"),
    (("baseline", "callback_contact", "value"), ""),
    (("baseline", "provenance", "source_kind"), "CURRENT_REQUEST"),
    (("baseline", "last_verified_at"), "2026-09-01T08:00:00Z"),
    (("baseline", "last_verified_at"), "2026-10-05T08:00:00Z"),
    (("baseline", "callback_contact", "last_verified_at"), "2026-09-01T08:00:00Z"),
    (("baseline", "callback_contact", "last_verified_at"), "2026-10-04T08:00:00Z"),
    (("baseline", "payment_identity", "routing_identifier"), "ROUTE"),
    (("evidence", "extraction", "provider"), None),
    (("evidence", "extraction", "operator_id"), "ai-pretending-to-be-human"),
    (("evidence", "extraction", "method"), "MANUAL"),
    (("evidence", "extraction", "extracted_at"), "2026-10-03T08:00:00Z"),
    (("evidence", "extraction", "failure_code"), "TIMEOUT"),
    (("evidence", "source_ids"), [uid(1), uid(1)]),
    (("evidence", "account_identifier", "status"), "MISSING"),
    (("evidence", "account_identifier", "status"), "AMBIGUOUS"),
    (("evidence", "account_identifier", "candidates"), []),
    (("evidence", "account_identifier", "candidates", 0, "value"), 123),
    (("evidence", "account_identifier", "candidates", 0, "value"), GB_IBAN),
    (("evidence", "account_identifier", "candidates", 0, "evidence", "source_id"), uid(99)),
    (("evidence", "account_identifier", "candidates", 0, "evidence", "field"), "bank_name"),
    (("evidence", "account_identifier", "candidates", 0, "evidence", "extracted_value"), GB_IBAN),
    (("evidence", "account_identifier", "candidates", 0, "evidence", "extraction_status"), "AMBIGUOUS"),
    (("evidence", "account_identifier", "candidates", 0, "evidence", "location", "char_start"), -1),
    (("evidence", "account_identifier", "candidates", 0, "evidence", "location", "char_end"), 0),
    (("evidence", "account_identifier", "candidates", 0, "evidence", "location", "page_number"), 3),
    (("review", "attempt_id"), uid(99)),
    (("review", "request_id"), uid(99)),
    (("review", "reviewed_evidence_ids"), []),
    (("review", "reviewed_evidence_ids"), [uid(9), uid(9)]),
    (("review", "reviewed_at"), "2026-10-04T07:00:00Z"),
    (("comparison", "state"), "VERIFIED"),
    (("comparison", "state"), "SAFE TO PAY"),
    (("comparison", "state"), "FRAUD"),
    (("comparison", "state"), "UNCHANGED"),
    (("comparison", "reason_codes"), []),
    (("comparison", "reason_codes"), ["FRAUD_LIKELY"]),
    (("comparison", "reason_codes"), ["DESTINATION_CHANGED", "DESTINATION_CHANGED"]),
    (("comparison", "review_id"), uid(99)),
    (("comparison", "baseline_revision_id"), uid(99)),
    (("comparison", "vendor_id"), uid(99)),
    (("comparison", "request_id"), uid(99)),
    (("comparison", "compared_at"), "2026-10-04T08:01:00Z"),
    (("comparison", "evidence_ids"), [uid(99)]),
    (("comparison", "differences"), []),
    (("comparison", "differences", 0, "status"), "MATCH"),
    (("comparison", "differences", 0, "evidence_ids"), []),
    (("verification", "human_confirmed"), False),
    (("verification", "human_confirmed"), 1),
    (("verification", "human_confirmed"), "true"),
    (("review", "destination_instructions_checked"), False),
    (("review", "destination_instructions_checked"), 1),
    (("review", "destination_instructions_checked"), "true"),
    (("verification", "comparison_id"), uid(99)),
    (("verification", "baseline_revision_id"), uid(99)),
    (("verification", "vendor_id"), uid(99)),
    (("verification", "trusted_contact_id"), uid(99)),
    (("verification", "trusted_contact_revision_id"), uid(99)),
    (("verification", "trusted_callback_value"), "number-from-current-request"),
    (("verification", "callback_method"), "PHONE_FROM_EMAIL"),
    (("verification", "callback_method"), "KNOWN_PORTAL"),
    (("verification", "trusted_source", "source_reference"), "current-invoice"),
    (("verification", "checked_identity"), identity(GB_IBAN)),
    (("verification", "what_was_checked"), "BANK_ACCOUNT_OWNERSHIP"),
    (("verification", "operator_id"), "  "),
    (("verification", "confirmed_at"), "2026-10-04T08:02:00Z"),
])
def test_malformed_examples_are_rejected(path, replacement):
    data = valid_case(verified=True)
    assign_path(data, path, replacement)
    with pytest.raises(ValidationError):
        parse(CaseContract, data)


@pytest.mark.parametrize("section,key", [
    ("evidence", "verified"), ("evidence", "fraud_probability"),
    ("evidence", "safe_to_pay"), ("evidence", "state"),
    ("comparison", "payment_approved"), ("verification", "ownership_verified"),
    ("baseline", "ai_trust_score"), ("review", "verified"),
])
def test_extra_fields_rejected(section, key):
    data = valid_case(verified=True)
    data[section][key] = True
    with pytest.raises(ValidationError):
        parse(CaseContract, data)


def test_excerpt_with_valid_local_shape_but_fabricated_source_is_rejected():
    data = valid_case()
    span = data["evidence"]["account_identifier"]["candidates"][0]["evidence"]
    span["location"]["char_start"] += 1
    span["location"]["char_end"] += 1
    parse(EvidenceSpan, span)  # Shape alone cannot authenticate a source reference.
    with pytest.raises(ValidationError, match="immutable source offsets"):
        parse(CaseContract, data)


def test_unknown_page_can_remain_absent_and_known_page_is_source_bound():
    data = valid_case()
    data["sources"][0]["page_number"] = 2
    data["evidence"]["account_identifier"]["candidates"][0]["evidence"]["location"]["page_number"] = 2
    assert parse(CaseContract, data).sources[0].page_number == 2


def test_ambiguity_and_contradictions_are_preserved_without_selecting_a_winner():
    data = valid_case("UNCERTAIN")
    text = f"Pay to {GB_IBAN}. Or pay to {DE_IBAN}."
    data["sources"][0]["text"] = text
    data["sources"][0]["sha256"] = hashlib.sha256(text.encode()).hexdigest()
    candidates = []
    for number, account in enumerate((GB_IBAN, DE_IBAN), 9):
        candidate = field(account, account, text, "account_identifier", number)["candidates"][0]
        candidate["evidence"]["extraction_status"] = "AMBIGUOUS"
        candidates.append(candidate)
    data["evidence"]["account_identifier"] = {"status": "AMBIGUOUS", "candidates": candidates}
    data["review"]["reviewed_evidence_ids"] = [uid(9), uid(10)]
    data["comparison"].update({
        "reason_codes": ["DESTINATION_AMBIGUOUS"], "missing_information": [],
        "evidence_ids": [uid(9), uid(10)],
        "contradictions": [{"field": "account_identifier", "explanation": "Conflicting instructions.", "evidence_ids": [uid(9), uid(10)]}],
    })
    assert parse(CaseContract, data).comparison.state == "UNCERTAIN"
    data["review"]["payment_identity"] = identity(GB_IBAN)
    with pytest.raises(ValidationError, match="unambiguous"):
        parse(CaseContract, data)


def test_missing_baseline_has_no_fabricated_identity():
    data = valid_case("UNCERTAIN")
    data["baseline"] = None
    data["comparison"].update({"baseline_revision_id": None, "baseline_identity": None, "differences": [], "reason_codes": ["BASELINE_UNAVAILABLE"]})
    assert parse(CaseContract, data).comparison.baseline_identity is None


def test_provider_failure_is_explicit_and_cannot_produce_verification():
    data = valid_case("UNCERTAIN")
    for name in list(data["evidence"]):
        if isinstance(data["evidence"][name], dict) and "status" in data["evidence"][name]:
            data["evidence"][name] = {"status": "UNREADABLE", "candidates": []}
    data["evidence"]["extraction"]["failure_code"] = "TIMEOUT"
    data["review"] = None
    data["comparison"].update({"review_id": None, "reason_codes": ["EXTRACTION_FAILED"]})
    assert parse(CaseContract, data).comparison.state == "UNCERTAIN"
    data["verification"] = valid_case(verified=True)["verification"]
    with pytest.raises(ValidationError, match="decisive comparison"):
        parse(CaseContract, data)


@pytest.mark.parametrize("method", ["MANUAL", "FIXTURE"])
def test_manual_and_fixture_attribution(method):
    data = valid_case()
    data["evidence"]["extraction"].update({"method": method, "operator_id": "demo-operator", "provider": None, "model": None, "prompt_version": None})
    assert parse(CaseContract, data).evidence.extraction.method == method


def test_context_fields_do_not_become_destination_changes():
    data = valid_case("UNCHANGED")
    name = "Different name"
    text = data["sources"][0]["text"] + f" Vendor: {name}"
    data["sources"][0]["text"] = text
    data["sources"][0]["sha256"] = hashlib.sha256(text.encode()).hexdigest()
    data["evidence"]["vendor_name"] = field(name, name, text, "vendor_name", 20)
    data["comparison"]["evidence_ids"].append(uid(20))
    data["comparison"]["differences"].append({"field": "vendor_name", "baseline_value": "Synthetic Vendor", "requested_value": name, "status": "CHANGED", "evidence_ids": [uid(20)]})
    assert parse(CaseContract, data).comparison.state == "UNCHANGED"


def test_supported_identity_does_not_make_separate_routing_supported():
    data = valid_case()
    data["baseline"]["routing_identifier"] = "ROUTING-FROM-PRIOR-RECORD"
    with pytest.raises(ValidationError, match="unsupported"):
        parse(CaseContract, data)


def test_models_are_frozen_and_python_inputs_are_strict():
    case = parse(CaseContract, valid_case())
    with pytest.raises(ValidationError):
        case.comparison.state = "UNCHANGED"
    with pytest.raises(ValidationError):
        CaseContract.model_validate(valid_case())  # JSON UUIDs/arrays are not typed Python values.


def test_ai_payload_contains_only_extracted_fields():
    data = valid_case()["evidence"]
    payload = {k: v for k, v in data.items() if k not in ("request_id", "source_ids", "extraction")}
    parse(ExtractionPayload, payload)
    payload["operator_id"] = "injected"
    with pytest.raises(ValidationError):
        parse(ExtractionPayload, payload)


@pytest.mark.parametrize("model", [
    TrustedVendorRecord, PaymentRequestEvidence, EvidenceSpan, NormalizedPaymentIdentity,
    ComparisonResult, HumanVerificationRecord, CaseContract, ExtractionPayload,
])
def test_json_schemas_export_without_untyped_objects(model):
    schema = model.model_json_schema()
    assert schema["additionalProperties"] is False
    assert all(definition.get("additionalProperties") is False for definition in schema.get("$defs", {}).values() if definition.get("type") == "object")


def test_unchanged_and_uncertain_reason_combinations_are_rejected():
    data = valid_case("UNCHANGED")["comparison"]
    data["reason_codes"] = ["DESTINATION_MATCH", "REVIEW_REQUIRED"]
    with pytest.raises(ValidationError):
        parse(ComparisonResult, data)
    data = valid_case("UNCERTAIN")["comparison"]
    data["reason_codes"] = ["DESTINATION_MATCH"]
    with pytest.raises(ValidationError):
        parse(ComparisonResult, data)


def test_unknown_difference_cannot_contain_two_known_values():
    with pytest.raises(ValidationError):
        parse(FieldDifference, {"field": "bank_name", "baseline_value": "A", "requested_value": "B", "status": "UNKNOWN", "evidence_ids": []})


def test_source_over_limit_is_rejected_before_comparison():
    source = valid_case()["sources"][0]
    source["text"] = "X" * 20_001
    source["sha256"] = hashlib.sha256(source["text"].encode()).hexdigest()
    with pytest.raises(ValidationError):
        parse(SourceDocument, source)


def test_boolean_claim_is_not_a_string_or_integer():
    data = valid_case()["evidence"]
    text = "Details changed"
    data["claims_details_changed"] = field("true", text, text, "claims_details_changed", 20)
    with pytest.raises(ValidationError):
        parse(PaymentRequestEvidence, data)


def test_evidence_ids_cannot_be_reused_across_fields():
    data = valid_case()["evidence"]
    data["invoice_number"] = field("INV-001", "INV-001", "INV-001", "invoice_number", 9)
    with pytest.raises(ValidationError, match="unique"):
        parse(PaymentRequestEvidence, data)


def test_not_configured_does_not_invent_model_or_operator():
    data = valid_case("UNCERTAIN")
    for observation in data["evidence"].values():
        if isinstance(observation, dict) and "status" in observation:
            observation.update({"status": "UNREADABLE", "candidates": []})
    data["evidence"]["extraction"].update({
        "method": "NOT_ATTEMPTED", "failure_code": "NOT_CONFIGURED",
        "provider": None, "model": None, "prompt_version": None,
    })
    data["review"] = None
    data["comparison"].update({"review_id": None, "reason_codes": ["EXTRACTION_FAILED"]})
    case = parse(CaseContract, data)
    assert case.evidence.extraction.provider is None
    assert case.evidence.extraction.operator_id is None
    data["evidence"]["extraction"]["method"] = "AI"
    with pytest.raises(ValidationError):
        parse(CaseContract, data)


@pytest.mark.parametrize("status", ["MISSING", "UNREADABLE", "UNSUPPORTED"])
def test_nonobservations_cannot_have_fabricated_evidence(status):
    data = valid_case()["evidence"]
    data["account_identifier"]["status"] = status
    with pytest.raises(ValidationError):
        parse(PaymentRequestEvidence, data)


def test_multiple_sources_must_fit_total_text_limit():
    data = valid_case()
    second = dict(data["sources"][0])
    second["source_id"] = uid(99)
    second["text"] = "X" * 20_000
    second["sha256"] = hashlib.sha256(second["text"].encode()).hexdigest()
    data["sources"].append(second)
    data["evidence"]["source_ids"].append(uid(99))
    with pytest.raises(ValidationError, match="total request"):
        parse(CaseContract, data)


def test_comparison_cannot_cite_account_evidence_for_other_field():
    data = valid_case()
    data["comparison"]["differences"].append({
        "field": "vendor_name", "baseline_value": "A", "requested_value": "B",
        "status": "CHANGED", "evidence_ids": [uid(9)],
    })
    with pytest.raises(ValidationError, match="compared field"):
        parse(CaseContract, data)


def test_missing_review_can_only_be_uncertain_with_review_reason():
    data = valid_case("UNCERTAIN")
    data["review"] = None
    data["comparison"].update({"review_id": None, "reason_codes": ["REVIEW_REQUIRED"]})
    assert parse(CaseContract, data).comparison.state == "UNCERTAIN"
    data["comparison"]["reason_codes"] = ["DESTINATION_MISSING"]
    with pytest.raises(ValidationError, match="missing review"):
        parse(CaseContract, data)


def test_no_provider_call_or_human_verification_is_implied_by_schema():
    # Presence of an accepted snapshot does not add an approval/verification state.
    case = parse(CaseContract, valid_case())
    assert case.verification is None
    assert case.evidence.extraction.method == "AI"
    assert case.comparison.state == "VERIFY"
