"""Validate authored labels and evidence, without measuring benchmark performance."""

import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from payproof.evaluation_contracts import BenchmarkCorpus

CORPUS_PATH = Path(__file__).resolve().parents[1] / "benchmarks/phase1-v1/cases.json"


def definition():
    return json.loads(CORPUS_PATH.read_text())


def validate(data):
    return BenchmarkCorpus.model_validate_json(json.dumps(data))


def test_thirty_authored_cases_are_grounded_and_not_evaluation_results():
    corpus = validate(definition())
    assert len(corpus.cases) == 30
    assert corpus.evaluation_status == "NOT_RUN"
    assert corpus.independent_label_review == "PENDING"
    assert corpus.split == "PUBLIC_DIAGNOSTIC_NOT_HELD_OUT"
    assert Counter(c.coverage_bucket for c in corpus.cases) == {
        "TRUE_CHANGE": 12,
        "NO_CONSEQUENTIAL_CHANGE": 8,
        "UNCERTAIN": 10,
    }
    assert Counter(c.after_gold_source_review.state for c in corpus.cases) == {
        "VERIFY": 10,
        "UNCHANGED": 7,
        "UNCERTAIN": 13,
    }
    assert Counter(c.ground_truth.destination_relation for c in corpus.cases) == {
        "CHANGED": 13,
        "UNCHANGED": 9,
        "UNRESOLVED": 8,
    }
    assert all(c.without_source_review.state == "UNCERTAIN" for c in corpus.cases)


def test_routing_bank_and_format_scope_are_explicit_not_optimized_away():
    cases = {c.case_id: c for c in validate(definition()).cases}
    assert cases["PP-03"].after_gold_source_review.state == "VERIFY"
    assert cases["PP-05"].ground_truth.consequential_changes[0].component == "iban_bank_component"
    for name in ("PP-07", "PP-08", "PP-29"):
        assert cases[name].ground_truth.destination_relation == "CHANGED"
        assert cases[name].ground_truth.phase1_comparable is False
        assert cases[name].after_gold_source_review.state == "UNCERTAIN"
    assert cases["PP-16"].after_gold_source_review.state == "UNCHANGED"
    for name in ("PP-20", "PP-30"):
        assert cases[name].ground_truth.destination_relation == "UNCHANGED"
        assert cases[name].after_gold_source_review.state == "UNCERTAIN"
        assert cases[name].normalized_gold_requested_identity is None
    assert cases["PP-19"].after_gold_source_review.state == "UNCHANGED"
    assert cases["PP-27"].baseline_key is None


def test_historical_reference_and_unreadable_region_do_not_invent_payment_values():
    cases = {c.case_id: c for c in validate(definition()).cases}
    retired = cases["PP-09"].non_destination_spans[0]
    assert retired.role == "HISTORICAL_DESTINATION"
    assert retired.raw_value != cases["PP-09"].gold_evidence.account_identifier.candidates[0].value
    irrelevant = cases["PP-12"].non_destination_spans[0]
    assert irrelevant.role == "IRRELEVANT_NUMBER"
    unreadable = cases["PP-24"].gold_evidence.account_identifier
    assert unreadable.status == "UNREADABLE" and unreadable.candidates == ()
    assert len(cases["PP-26"].sources) == 2
    assert len(cases["PP-26"].gold_evidence.account_identifier.candidates) == 2
    migration = cases["PP-09"].gold_evidence
    assert migration.stated_reason_for_change.status == "FOUND"
    assert migration.claims_details_changed.candidates[0].value is True


@pytest.mark.parametrize(
    "mutation",
    [
        "invented_quote",
        "duplicate_id",
        "unknown_baseline",
        "wrong_vendor",
        "invented_normalized_identity",
        "missing_history_promoted",
        "incorrect_decisive_label",
        "equal_change_values",
        "pretend_results",
        "invented_exclusion",
        "unreviewed_decision",
        "too_few_cases",
        "real_provenance",
    ],
)
def test_malformed_case_definitions_are_rejected(mutation):
    data = deepcopy(definition())
    case = data["cases"][0]
    if mutation == "invented_quote":
        case["gold_evidence"]["account_identifier"]["candidates"][0]["evidence"][
            "exact_excerpt"
        ] = "invented"
    elif mutation == "duplicate_id":
        data["cases"][1]["case_id"] = case["case_id"]
    elif mutation == "unknown_baseline":
        case["baseline_key"] = "invented"
    elif mutation == "wrong_vendor":
        case["selected_vendor_id"] = "00000000-0000-4000-8000-000000000001"
    elif mutation == "invented_normalized_identity":
        case["normalized_gold_requested_identity"]["account_identifier"] = data["baselines"][0][
            "record"
        ]["payment_identity"]["account_identifier"]
    elif mutation == "missing_history_promoted":
        data["cases"][26]["after_gold_source_review"] = {
            "state": "UNCHANGED",
            "reason_codes": ["DESTINATION_MATCH"],
        }
    elif mutation == "incorrect_decisive_label":
        case["after_gold_source_review"] = {
            "state": "UNCHANGED",
            "reason_codes": ["DESTINATION_MATCH"],
        }
    elif mutation == "equal_change_values":
        change = case["ground_truth"]["consequential_changes"][0]
        change["requested_value"] = change["trusted_value"]
    elif mutation == "pretend_results":
        data["observed_accuracy"] = 1.0
    elif mutation == "invented_exclusion":
        data["cases"][8]["non_destination_spans"][0]["raw_value"] = "invented"
    elif mutation == "unreviewed_decision":
        case["without_source_review"] = {"state": "VERIFY", "reason_codes": ["DESTINATION_CHANGED"]}
    elif mutation == "too_few_cases":
        data["cases"] = data["cases"][:19]
    elif mutation == "real_provenance":
        data["baselines"][0]["record"]["provenance"]["source_kind"] = "PRIOR_VENDOR_RECORD"
    with pytest.raises(ValidationError):
        validate(data)


def test_exported_json_schema_matches_contract():
    path = CORPUS_PATH.with_name("schema.json")
    assert json.loads(path.read_text()) == BenchmarkCorpus.model_json_schema()
