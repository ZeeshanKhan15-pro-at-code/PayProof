"""Safety-bearing skeleton checks: config, inputs, corpus, and read-only startup."""

import json
import os
import secrets
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from payproof.benchmark import validate_corpus
from payproof.cli import main
from payproof.comparison import compare
from payproof.config import ConfigurationError, load_settings
from payproof.documents import capture_text
from payproof.extraction import extract_document
from payproof.fixtures import FixtureCorpus, load_corpus
from payproof.provenance import source_digest
from payproof.schemas import CaseContract
from payproof.web import create_app


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for key in tuple(os.environ):
        if key.startswith("PAYPROOF_"):
            monkeypatch.delenv(key)


def test_default_startup_has_no_secret_provider_or_storage_side_effect(tmp_path):
    destination = tmp_path / "not-created"
    settings = load_settings({"PAYPROOF_DATA_DIR": str(destination)})
    app = create_app(settings)
    assert app.test_client().get("/healthz").json["stage"] == "skeleton"
    assert settings.secret_key is None
    assert settings.extraction_mode == "disabled"
    assert not destination.exists()
    assert not app.debug


@pytest.mark.parametrize(
    "environment",
    [
        {"PAYPROOF_ENV": "production"},
        {"PAYPROOF_ENV": "production", "PAYPROOF_SECRET_KEY": "short"},
        {"PAYPROOF_ENV": "production", "PAYPROOF_SECRET_KEY": " " * 40},
        {"PAYPROOF_ENV": "not-an-environment"},
        {"PAYPROOF_EXTRACTION_MODE": "live"},
        {"PAYPROOF_PORT": "8000oops"},
        {"PAYPROOF_PORT": "８０００"},
        {"PAYPROOF_PORT": "80"},
        {"PAYPROOF_PORT": "65536"},
        {"PAYPROOF_DATA_DIR": " "},
        {"PAYPROOF_UNKNOWN": "value"},
    ],
)
def test_invalid_environment_is_rejected(environment):
    with pytest.raises(ConfigurationError):
        load_settings(environment)


def test_secret_is_never_part_of_dump_repr_or_cli_error(capsys, monkeypatch):
    generated = secrets.token_urlsafe(48)
    settings = load_settings({"PAYPROOF_ENV": "production", "PAYPROOF_SECRET_KEY": generated})
    assert generated not in repr(settings)
    assert "secret_key" not in settings.model_dump()
    app = create_app(settings)
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert generated not in json.dumps(app.test_client().get("/").json)
    monkeypatch.setenv("PAYPROOF_ENV", generated)
    assert main(["check"]) == 1
    assert generated not in capsys.readouterr().err


@pytest.mark.parametrize("text", ["", " \t\n", "X" * 20_001])
def test_document_capture_rejects_empty_or_oversize_source(text):
    with pytest.raises(ValidationError):
        capture_text(text, operator_id="operator")


def test_document_capture_preserves_exact_unicode_text_and_server_metadata():
    text = "Invoice\nPay to ＧB82.\r\n"
    first = capture_text(text, operator_id="operator", kind="INVOICE")
    second = capture_text(text, operator_id="operator", kind="INVOICE")
    assert first.text == text
    assert first.sha256 == source_digest(text)
    assert first.source_id != second.source_id
    assert first.captured_at.utcoffset().total_seconds() == 0
    assert first.page_number is None


def test_corpus_links_all_requests_to_synthetic_trusted_baselines():
    corpus = load_corpus()
    assert len(corpus.vendors) == 3
    assert len(corpus.requests) == 9
    assert all(v.provenance.source_kind == "SYNTHETIC_FIXTURE" for v in corpus.vendors)
    assert all(r.evidence.extraction.method == "FIXTURE" for r in corpus.requests)
    assert {r.expected_state_after_review for r in corpus.requests} == {
        "UNCHANGED",
        "VERIFY",
        "UNCERTAIN",
    }
    assert {r.source.kind for r in corpus.requests} == {
        "EMAIL",
        "INVOICE",
        "VENDOR_NOTICE",
        "PLAIN_TEXT",
    }
    assert (
        next(
            r for r in corpus.requests if r.fixture_id == "conflicting-destinations"
        ).evidence.account_identifier.status
        == "AMBIGUOUS"
    )


def test_benchmark_reports_gold_comparison_without_ai_accuracy_claims():
    report = validate_corpus()
    assert report.requests_validated == 9
    assert report.comparison_evaluation == "PASS"
    assert report.comparisons_evaluated == 9
    assert report.comparison_mismatches == ()
    assert report.false_unchanged == 0
    assert report.review_mode == "SIMULATED_FIXTURE_REVIEW"
    assert report.release_corpus_complete is False
    assert report.ai_evaluation == "NOT_IMPLEMENTED"
    assert report.expected_outcomes == {"UNCHANGED": 2, "VERIFY": 3, "UNCERTAIN": 4}
    assert report.elapsed_ms >= 0


def test_benchmark_labels_cannot_drive_engine_decisions_and_mismatch_fails_cli(monkeypatch, capsys):
    corpus = load_corpus()
    matched = next(r for r in corpus.requests if r.fixture_id == "unchanged")
    mislabeled = matched.model_copy(
        update={
            "expected_state_after_review": "VERIFY",
            "expected_reason_codes": ("DESTINATION_CHANGED",),
        }
    )
    monkeypatch.setattr(
        "payproof.benchmark.load_corpus", lambda: FixtureCorpus(corpus.vendors, (mislabeled,))
    )
    report = validate_corpus()
    assert report.comparison_evaluation == "FAIL"
    assert report.comparison_mismatches == ("unchanged",)
    assert report.false_unchanged == 1
    assert main(["benchmark"]) == 1
    assert json.loads(capsys.readouterr().out)["comparison_evaluation"] == "FAIL"


def test_unreviewed_input_cannot_return_a_decisive_comparison():
    corpus = load_corpus()
    request = corpus.requests[0]
    baseline = next(v for v in corpus.vendors if v.revision_id == request.baseline_revision_id)
    case = CaseContract(sources=(request.source,), evidence=request.evidence, baseline=baseline)
    assert extract_document(request.source).extraction.failure_code == "NOT_CONFIGURED"
    result = compare(
        case,
        comparison_id=uuid4(),
        compared_at=request.evidence.extraction.extracted_at + timedelta(minutes=1),
    )
    assert result.state == "UNCERTAIN"
    assert "REVIEW_REQUIRED" in result.reason_codes
    assert result.requested_identity is None


@pytest.mark.parametrize("route", ["/", "/healthz", "/verify", "/cases"])
def test_debug_interface_has_no_write_routes(route):
    client = create_app(load_settings({})).test_client()
    assert client.post(route, json={"state": "VERIFIED"}).status_code in (404, 405)


def test_debug_routes_do_not_serve_document_or_bank_content():
    client = create_app(load_settings({})).test_client()
    assert client.get("/").json["writable"] is False
    for route in ("/", "/healthz"):
        body = client.get(route).text
        for vendor in load_corpus().vendors:
            assert vendor.payment_identity.account_identifier not in body


@pytest.mark.parametrize("command", ["check", "debug", "benchmark"])
def test_cli_is_offline_json_and_creates_no_database(command, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PAYPROOF_DATA_DIR", str(tmp_path / "data"))
    assert main([command]) == 0
    output = json.loads(capsys.readouterr().out)
    assert isinstance(output, dict)
    assert not (tmp_path / "data").exists()
