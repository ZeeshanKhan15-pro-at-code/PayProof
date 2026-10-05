"""Environment-driven live HTTP integration; all provider responses are mocked."""

import json
import secrets
from urllib.error import HTTPError, URLError

import pytest
from test_extraction import envelope, install_response, wire_payload
from test_extraction import forbid_real_network as forbid_real_network

from payproof.config import ConfigurationError, load_settings
from payproof.documents import capture_text
from payproof.extraction import ExtractionInputError, extract_attempt
from payproof.openai_extraction import API_URL
from payproof.schemas import EVIDENCE_FIELDS, CaseContract


@pytest.fixture
def configured_environment(monkeypatch):
    import os

    for name in tuple(os.environ):
        if name.startswith("PAYPROOF_"):
            monkeypatch.delenv(name)
    key = secrets.token_urlsafe(32)
    monkeypatch.setenv("PAYPROOF_EXTRACTION_MODE", "live")
    monkeypatch.setenv("PAYPROOF_PROVIDER_API_KEY", key)
    monkeypatch.setenv("PAYPROOF_PROVIDER_MODEL", "synthetic-requested-model")
    monkeypatch.setenv("PAYPROOF_EXTRACTION_TIMEOUT_SECONDS", "9")
    return key


def pair():
    return (
        capture_text(
            "From: billing@synthetic.example\nPlease use the attached invoice.",
            kind="EMAIL",
            operator_id="synthetic-live-qa",
        ),
        capture_text(
            "Invoice: LIVE-001\nAmount: 1250.00 GBP\nPay to IBAN GB57TEST00000000009928.",
            kind="INVOICE",
            operator_id="synthetic-live-qa",
        ),
    )


def test_environment_live_pair_success_has_exact_grounding_and_no_baseline(
    monkeypatch, configured_environment
):
    sources = pair()
    payload = wire_payload(
        sources,
        {
            "sender_email": [(0, "billing@synthetic.example", "billing@synthetic.example")],
            "invoice_number": [(1, "LIVE-001", "LIVE-001")],
            "account_identifier": [(1, "GB57TEST00000000009928", "GB57TEST00000000009928")],
        },
    )
    calls, _, _, _ = install_response(monkeypatch, envelope(payload))
    attempt = extract_attempt(sources)  # Reads process environment, not fixture settings.
    evidence = attempt.evidence
    assert evidence.extraction.failure_code is None and evidence.extraction.method == "AI"
    assert evidence.extraction.model == "synthetic-reported-model"
    CaseContract(sources=sources, evidence=evidence, baseline=None)
    span = evidence.account_identifier.candidates[0].evidence
    assert span.source_id == sources[1].source_id
    assert sources[1].text[span.location.char_start : span.location.char_end] == span.exact_excerpt
    assert span.extracted_value == "GB57TEST00000000009928"
    assert evidence.reply_to.status == "MISSING" and not evidence.reply_to.candidates
    body = json.loads(calls[0][0].data)
    documents = json.loads(body["input"][0]["content"])["documents"]
    assert all(set(document) == {"source_id", "kind", "text"} for document in documents)
    assert body["text"]["format"]["strict"] is True
    assert body["tools"] == [] and body["store"] is False
    assert calls[0][1] == 9 and len(calls) == 1
    assert configured_environment not in calls[0][0].data.decode()
    assert configured_environment not in evidence.model_dump_json()


@pytest.mark.parametrize(
    "variant, expected",
    [
        ("malformed", "INVALID_RESPONSE"),
        ("schema", "INVALID_RESPONSE"),
        ("fabricated", "EVIDENCE_INVALID"),
        ("verdict", "INVALID_RESPONSE"),
    ],
)
def test_environment_live_rejects_entire_invalid_response(
    monkeypatch, configured_environment, variant, expected
):
    sources = pair()
    payload = wire_payload(
        sources, {"account_identifier": [(1, "GB57TEST00000000009928", "GB57TEST00000000009928")]}
    )
    response = envelope(payload)
    if variant == "malformed":
        response["output"][0]["content"][0]["text"] = "{broken"
    elif variant == "schema":
        del payload["reply_to"]
        response = envelope(payload)
    elif variant == "fabricated":
        payload["account_identifier"]["candidates"][0]["exact_excerpt"] = (
            "Invented payment instruction."
        )
        response = envelope(payload)
    else:
        payload["state"] = "VERIFIED"
        response = envelope(payload)
    calls, _, _, _ = install_response(monkeypatch, response)
    attempt = extract_attempt(sources)
    assert attempt.evidence.extraction.failure_code == expected
    assert len(calls) == 1
    assert all(
        getattr(attempt.evidence, name).status == "UNREADABLE"
        and not getattr(attempt.evidence, name).candidates
        for name in EVIDENCE_FIELDS
    )


@pytest.mark.parametrize(
    "failure, expected",
    [
        (TimeoutError("synthetic timeout"), "TIMEOUT"),
        (URLError("synthetic network error"), "PROVIDER_UNAVAILABLE"),
        (
            HTTPError(API_URL, 400, "synthetic invalid model/schema", None, None),
            "PROVIDER_UNAVAILABLE",
        ),
        (HTTPError(API_URL, 503, "synthetic provider error", None, None), "PROVIDER_UNAVAILABLE"),
    ],
)
def test_environment_live_transport_failure_has_no_fixture_fallback(
    monkeypatch, configured_environment, failure, expected
):
    from payproof.fixtures import load_corpus

    request = next(r for r in load_corpus().requests if r.fixture_id == "demo-account-change")
    source = capture_text(
        request.source.text, kind=request.source.kind, operator_id="synthetic-live-qa"
    )
    calls = []

    class Opener:
        def open(self, request, *, timeout):
            calls.append(request)
            raise failure

    monkeypatch.setattr("payproof.openai_extraction.build_opener", lambda *args: Opener())
    attempt = extract_attempt((source,))
    assert attempt.evidence.extraction.method == "AI"
    assert attempt.evidence.extraction.failure_code == expected and len(calls) == 1
    assert attempt.raw_provider_response is None
    assert all(not getattr(attempt.evidence, name).candidates for name in EVIDENCE_FIELDS)


def test_environment_live_valid_partial_data_preserves_missing(monkeypatch, configured_environment):
    sources = pair()
    calls, _, _, _ = install_response(
        monkeypatch,
        envelope(wire_payload(sources, {"invoice_number": [(1, "LIVE-001", "LIVE-001")]})),
    )
    attempt = extract_attempt(sources)
    assert attempt.evidence.extraction.failure_code is None
    assert attempt.evidence.invoice_number.status == "FOUND"
    assert attempt.evidence.account_identifier.status == "MISSING"
    assert attempt.evidence.claims_details_changed.status == "MISSING"
    assert attempt.evidence.reply_to.status == "MISSING"
    assert len(calls) == 1


@pytest.mark.parametrize("location", ["model", "output", "ignored_field", "escaped_output"])
def test_provider_credential_echo_is_never_returned_or_retained(
    monkeypatch, configured_environment, location, capsys
):
    source = capture_text("No payment details.", operator_id="synthetic-live-qa")
    response = envelope(wire_payload((source,), {}))
    if location == "model":
        response["model"] = configured_environment
    elif location == "output":
        response["output"][0]["content"][0]["text"] = configured_environment
    elif location == "ignored_field":
        response["ignored_field"] = configured_environment
    else:
        escaped = "".join(f"\\u{ord(char):04x}" for char in configured_environment)
        response["output"][0]["content"][0]["text"] = '{"api_key": "' + escaped + '"}'
    install_response(monkeypatch, response)
    attempt = extract_attempt((source,))
    assert attempt.evidence.extraction.failure_code == "INVALID_RESPONSE"
    assert attempt.raw_provider_response is None
    assert configured_environment not in attempt.evidence.model_dump_json()
    assert configured_environment not in repr(attempt)
    assert not capsys.readouterr().out


def test_credential_in_source_is_rejected_before_upload(monkeypatch, configured_environment):
    source = capture_text(
        "Accidental credential: " + configured_environment, operator_id="synthetic-live-qa"
    )
    with pytest.raises(ExtractionInputError) as stopped:
        extract_attempt((source,))
    assert configured_environment not in str(stopped.value)


def test_credential_in_model_configuration_is_rejected_without_echo(configured_environment):
    with pytest.raises(ConfigurationError) as stopped:
        load_settings(
            {
                "PAYPROOF_EXTRACTION_MODE": "live",
                "PAYPROOF_PROVIDER_API_KEY": configured_environment,
                "PAYPROOF_PROVIDER_MODEL": "accidental-" + configured_environment,
            }
        )
    assert configured_environment not in str(stopped.value)


@pytest.mark.parametrize("missing", ["mode", "key", "model"])
def test_live_smoke_reports_not_configured_without_network(
    monkeypatch, configured_environment, missing, capsys
):
    from scripts.smoke_live_extraction import main

    name = {
        "mode": "PAYPROOF_EXTRACTION_MODE",
        "key": "PAYPROOF_PROVIDER_API_KEY",
        "model": "PAYPROOF_PROVIDER_MODEL",
    }[missing]
    monkeypatch.delenv(name)
    assert main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "NOT_CONFIGURED",
        "provider_called": False,
    }


@pytest.mark.parametrize("name", [".env.example", "README.md"])
def test_source_distribution_does_not_ship_environment_files(tmp_path, name):
    import io
    import tarfile

    from scripts.check_wheel import check_source_archive

    path = tmp_path / "synthetic-source.tar.gz"
    content = b"Synthetic source material."
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo("synthetic/" + name)
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
    if name.startswith(".env"):
        with pytest.raises(RuntimeError) as stopped:
            check_source_archive(path)
        assert "Synthetic source material" not in str(stopped.value)
    else:
        check_source_archive(path)


def test_literal_json_like_source_value_is_not_reparsed_as_model_output(
    monkeypatch, configured_environment
):
    source = capture_text("[masked account]", operator_id="synthetic-live-qa")
    payload = wire_payload(
        (source,), {"account_identifier": [(0, "[masked account]", "[masked account]")]}
    )
    install_response(monkeypatch, envelope(payload))
    attempt = extract_attempt((source,))
    assert attempt.evidence.extraction.failure_code is None
    assert attempt.evidence.account_identifier.candidates[0].value == "[masked account]"
