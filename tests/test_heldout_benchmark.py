"""Definition checks only for held-out data. Metric tests use diagnostic data.

Never execute a predictor on the held-out cases in the development test suite.
"""

import hashlib
import json
import shutil
from collections import Counter

import pytest
from pydantic import ValidationError

from payproof.benchmark_harness import (
    DEFAULT_CORPUS,
    AttemptRecord,
    evaluate_track,
    run_benchmark,
    wire_schema_status,
)
from payproof.evaluation_contracts import BenchmarkCorpus, HeldOutCorpus
from payproof.extraction import ExtractionAttempt
from payproof.heldout_benchmark import (
    DEFAULT_ROOT,
    extended_metrics,
    fraction,
    load_frozen,
    main,
)
from payproof.schemas import EVIDENCE_FIELDS, PaymentRequestEvidence
from scripts.compile_heldout import compile_definition


def forbidden(*args, **kwargs):
    raise AssertionError("Held-out design validation must not execute predictors")


def test_heldout_definitions_frozen_grounded_and_disjoint(monkeypatch):
    monkeypatch.setattr("payproof.benchmark_harness.compare", forbidden)
    monkeypatch.setattr("payproof.benchmark_harness.extract_attempt", forbidden)
    corpus = load_frozen(DEFAULT_ROOT)
    assert corpus.evaluation_status == "NOT_RUN"
    assert corpus.independent_label_review == "PENDING"
    assert corpus.tuning_policy == "NO_OPTIMIZATION_ON_V1"
    assert len(corpus.cases) == 72
    assert Counter(c.after_gold_source_review.state for c in corpus.cases) == {
        "UNCHANGED": 15,
        "VERIFY": 24,
        "UNCERTAIN": 33,
    }
    assert Counter(c.ground_truth.destination_relation for c in corpus.cases) == {
        "UNCHANGED": 16,
        "CHANGED": 24,
        "UNRESOLVED": 32,
    }
    assert len({c.tags[0] for c in corpus.cases}) == 18
    assert set(Counter(c.tags[0] for c in corpus.cases).values()) == {4}
    old = BenchmarkCorpus.model_validate_json(DEFAULT_CORPUS.read_bytes())
    old_sources = {s.sha256 for c in old.cases for s in c.sources}
    assert not old_sources.intersection(s.sha256 for c in corpus.cases for s in c.sources)
    old_accounts = {b.record.payment_identity.account_identifier for b in old.baselines}
    old_accounts.update(
        x.value for c in old.cases for x in c.gold_evidence.account_identifier.candidates
    )
    assert not old_accounts.intersection(
        x.value for c in corpus.cases for x in c.gold_evidence.account_identifier.candidates
    )
    for field in EVIDENCE_FIELDS:
        assert any(getattr(c.gold_evidence, field).candidates for c in corpus.cases)
        assert any(getattr(c.gold_evidence, field).status == "MISSING" for c in corpus.cases)
    assert all(c.without_source_review.state == "UNCERTAIN" for c in corpus.cases)
    assert all(b.record.provenance.source_kind == "SYNTHETIC_FIXTURE" for b in corpus.baselines)


def test_compilation_is_mechanical_and_labels_precede_prediction(monkeypatch):
    monkeypatch.setattr("payproof.benchmark_harness.compare", forbidden)
    monkeypatch.setattr("payproof.benchmark_harness.extract_attempt", forbidden)
    original = (DEFAULT_ROOT / "cases.json").read_text()
    authored = json.loads((DEFAULT_ROOT / "authoring.json").read_text())
    compiled = compile_definition(authored)
    assert compiled.model_dump_json(indent=2) + "\n" == original
    assert (
        json.loads((DEFAULT_ROOT / "schema.json").read_text()) == HeldOutCorpus.model_json_schema()
    )
    for a, c in zip(authored["cases"], compiled.cases, strict=True):
        assert c.after_gold_source_review.state == a["expected_state"]
        assert list(c.after_gold_source_review.reason_codes) == a["expected_reason_codes"]
        assert c.ground_truth.destination_relation == a["destination_relation"]


@pytest.mark.parametrize("name", ["authoring.json", "cases.json", "schema.json"])
def test_freeze_rejects_changes_without_relabeling(tmp_path, name):
    root = tmp_path / "corpus"
    shutil.copytree(DEFAULT_ROOT, root)
    with (root / name).open("a") as out:
        out.write(" ")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_frozen(root)


@pytest.mark.parametrize("mutation", ["short", "decision", "quote", "label", "duplicate"])
def test_malformed_heldout_definitions_are_rejected(mutation):
    data = json.loads((DEFAULT_ROOT / "cases.json").read_text())
    if mutation == "short":
        data["cases"] = data["cases"][:59]
    elif mutation == "decision":
        data["cases"][0]["after_gold_source_review"]["state"] = "VERIFIED"
    elif mutation == "quote":
        data["cases"][0]["gold_evidence"]["account_identifier"]["candidates"][0]["evidence"][
            "exact_excerpt"
        ] = "invented"
    elif mutation == "label":
        data["cases"][0]["after_gold_source_review"] = {
            "state": "VERIFY",
            "reason_codes": ["DESTINATION_CHANGED"],
        }
    else:
        data["cases"][1]["case_id"] = data["cases"][0]["case_id"]
    with pytest.raises(ValidationError):
        HeldOutCorpus.model_validate_json(json.dumps(data))


def test_default_cli_is_validation_only(monkeypatch, capsys):
    monkeypatch.setattr("payproof.heldout_benchmark.run_benchmark", forbidden)
    monkeypatch.setattr("payproof.heldout_benchmark.load_settings", forbidden)
    assert main([]) == 0
    assert "predictions NOT_RUN" in capsys.readouterr().out


def test_live_forbids_fixture_fallback_before_prediction(monkeypatch, tmp_path):
    monkeypatch.setenv("PAYPROOF_EXTRACTION_MODE", "fixture")
    monkeypatch.setattr("payproof.heldout_benchmark.run_benchmark", forbidden)
    output = tmp_path / "new"
    assert main(["--live", "--output", str(output)]) == 2
    assert not output.exists()


def test_existing_run_directory_cannot_be_overwritten(monkeypatch, tmp_path):
    monkeypatch.setattr("payproof.heldout_benchmark.run_benchmark", forbidden)
    assert main(["--evaluate-gold", "--output", str(tmp_path)]) == 2


def test_gold_only_metrics_do_not_claim_extraction():
    # Diagnostic data only. Do not substitute held-out gold as model predictions.
    corpus = BenchmarkCorpus.model_validate_json(DEFAULT_CORPUS.read_bytes())
    report = run_benchmark(DEFAULT_CORPUS)
    assert extended_metrics(report, corpus) == {"status": "NOT_RUN", "extraction_metrics": None}
    assert fraction(0, 0) == {"numerator": None, "denominator": 0}


def diagnostic_report_with_attempts(attempts):
    corpus = BenchmarkCorpus.model_validate_json(DEFAULT_CORPUS.read_bytes())
    report = run_benchmark(DEFAULT_CORPUS)
    pipeline = evaluate_track(corpus, "conditional_pipeline", attempts)
    return corpus, report.model_copy(
        update={"tracks": report.tracks + (pipeline,), "extraction_attempts": attempts}
    )


def test_failed_extractions_remain_in_all_field_recall_denominators():
    corpus = BenchmarkCorpus.model_validate_json(DEFAULT_CORPUS.read_bytes())
    attempts = tuple(
        AttemptRecord(
            case_id=c.case_id, evidence=None, exception_type="TimeoutError", elapsed_seconds=0.0
        )
        for c in corpus.cases
    )
    corpus, report = diagnostic_report_with_attempts(attempts)
    metrics = extended_metrics(report, corpus)
    assert metrics["end_to_end_state_accuracy"] == {"numerator": 0, "denominator": 30}
    assert metrics["correct_UNCERTAIN"]["numerator"] == 0
    assert metrics["schema_failure_rate"] == {"numerator": None, "denominator": 0}
    assert metrics["schema_unassessable_count"] == 30
    assert metrics["extraction_failed_cases"] == 30
    assert metrics["field_accuracy"]["account_identifier"]["value_recall"]["numerator"] == 0
    assert metrics["field_accuracy"]["account_identifier"]["value_recall"]["denominator"] > 0
    assert all(
        metrics["full_attempt_field_status_accuracy"][f] == {"numerator": 0, "denominator": 30}
        for f in EVIDENCE_FIELDS
    )


def test_omission_decreases_field_recall_even_when_schema_valid():
    corpus = BenchmarkCorpus.model_validate_json(DEFAULT_CORPUS.read_bytes())
    records = []
    for c in corpus.cases:
        data = c.gold_evidence.model_dump(mode="json")
        data["account_identifier"] = {"status": "MISSING", "candidates": []}
        evidence = PaymentRequestEvidence.model_validate_json(json.dumps(data))
        records.append(
            AttemptRecord(
                case_id=c.case_id, evidence=evidence, elapsed_seconds=0.0, wire_schema_status="PASS"
            )
        )
    corpus, report = diagnostic_report_with_attempts(tuple(records))
    metrics = extended_metrics(report, corpus)
    assert metrics["schema_failure_rate"] == {"numerator": 0, "denominator": 30}
    assert metrics["consequential_change_recall"]["numerator"] == 0
    assert metrics["critical_false_UNCHANGED"] == 0
    assert metrics["field_accuracy"]["account_identifier"]["value_recall"]["numerator"] == 0
    assert metrics["extraction_error_cases"] > 0


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("fixture", "UNAVAILABLE"),
        ("schema", "FAIL"),
        ("protocol", "UNAVAILABLE"),
        ("grounding", "PASS"),
    ],
)
def test_schema_diagnostics_do_not_invent_provider_results(mode, expected):
    corpus = BenchmarkCorpus.model_validate_json(DEFAULT_CORPUS.read_bytes())
    evidence = corpus.cases[0].gold_evidence
    raw = None
    if mode != "fixture":
        data = evidence.model_dump(mode="json")
        data["extraction"].update(
            method="AI",
            operator_id=None,
            provider="openai",
            model="mock-model",
            prompt_version="mock",
            failure_code="EVIDENCE_INVALID" if mode == "grounding" else "INVALID_RESPONSE",
        )
        for f in EVIDENCE_FIELDS:
            data[f] = {"status": "UNREADABLE", "candidates": []}
        evidence = PaymentRequestEvidence.model_validate_json(json.dumps(data))
        if mode == "schema":
            raw = json.dumps(
                {
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "{}"}],
                        }
                    ]
                }
            ).encode()
    attempt = ExtractionAttempt(evidence=evidence, source_digests=(), raw_provider_response=raw)
    assert wire_schema_status(attempt) == expected


def test_no_results_exist_in_frozen_corpus():
    names = {p.name for p in DEFAULT_ROOT.iterdir()}
    assert names == {"authoring.json", "cases.json", "schema.json", "freeze.json"}
    manifest = json.loads((DEFAULT_ROOT / "freeze.json").read_text())
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((DEFAULT_ROOT / name).read_bytes()).hexdigest() == digest
