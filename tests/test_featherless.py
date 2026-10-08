"""Mocked chat-completions tests; not live model results."""

import json
import secrets
from urllib.error import URLError

import pytest
from test_extraction import install_response, wire_payload

from payproof.config import ConfigurationError, load_settings
from payproof.documents import capture_text
from payproof.extraction import extract_attempt
from payproof.schemas import EVIDENCE_FIELDS


def settings():
    return load_settings(
        {
            "PAYPROOF_EXTRACTION_MODE": "live",
            "PAYPROOF_PROVIDER": "featherless",
            "PAYPROOF_PROVIDER_BASE_URL": "https://api.featherless.ai/v1",
            "PAYPROOF_PROVIDER_MODEL": "synthetic-model",
            "PAYPROOF_PROVIDER_API_KEY": secrets.token_urlsafe(32),
        }
    )


def response(payload):
    return {
        "model": "synthetic-model",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(payload)},
            }
        ],
    }


@pytest.mark.parametrize(
    "variant",
    ["success", "partial", "malformed", "hallucination", "verdict", "truncated", "multiple"],
)
def test_chat_pipeline(monkeypatch, variant):
    sources = (capture_text("Pay to IBAN GB57TEST00000000009928.", operator_id="test"),)
    payload = wire_payload(
        sources,
        {}
        if variant == "partial"
        else {"account_identifier": [(0, "GB57TEST00000000009928", "GB57TEST00000000009928")]},
    )
    if variant == "hallucination":
        payload["account_identifier"]["candidates"][0]["exact_excerpt"] = "fabricated"
    if variant == "verdict":
        payload["state"] = "VERIFIED"
    body = response(payload)
    if variant == "malformed":
        body["choices"][0]["message"]["content"] = "{broken"
    if variant == "truncated":
        body["choices"][0]["finish_reason"] = "length"
    if variant == "multiple":
        body["choices"].append(body["choices"][0])
    calls, _, _, _ = install_response(monkeypatch, body)
    evidence = extract_attempt(sources, settings=settings()).evidence
    request = calls[0][0]
    assert request.full_url == "https://api.featherless.ai/v1/chat/completions"
    sent = json.loads(request.data)
    assert sent["response_format"] == {"type": "json_object"}
    assert "baseline" not in sent["messages"][1]["content"]
    assert len(calls) == 1 and evidence.extraction.provider == "featherless"
    if variant in ("success", "partial"):
        assert evidence.extraction.failure_code is None
        assert evidence.reply_to.status == "MISSING"
    else:
        assert evidence.extraction.failure_code == (
            "EVIDENCE_INVALID" if variant == "hallucination" else "INVALID_RESPONSE"
        )
        assert all(getattr(evidence, f).status == "UNREADABLE" for f in EVIDENCE_FIELDS)


@pytest.mark.parametrize(
    "error,code", [(TimeoutError(), "TIMEOUT"), (URLError("network"), "PROVIDER_UNAVAILABLE")]
)
def test_network_fail_closed(monkeypatch, error, code):
    class Opener:
        def open(self, *args, **kwargs):
            raise error

    monkeypatch.setattr("payproof.openai_extraction.build_opener", lambda *args: Opener())
    result = extract_attempt(
        (capture_text("No destination", operator_id="test"),), settings=settings()
    )
    assert result.evidence.extraction.failure_code == code
    assert result.evidence.extraction.method == "AI"


@pytest.mark.parametrize(
    "url",
    [
        "http://api.featherless.ai/v1",
        "https://evil.example/v1",
        "https://api.featherless.ai/v1?key=bad",
    ],
)
def test_provider_url_cannot_redirect_credentials(url):
    with pytest.raises(ConfigurationError):
        load_settings({"PAYPROOF_PROVIDER": "featherless", "PAYPROOF_PROVIDER_BASE_URL": url})


def test_mocked_live_extraction_reaches_real_comparator(monkeypatch):
    from payproof.cases import complete_case, review_case
    from payproof.demo_proof import load_demo
    from payproof.schemas import CaseContract

    baseline = load_demo().vendor
    sources = (capture_text("Pay to IBAN GB57TEST00000000009928.", operator_id="test"),)
    payload = wire_payload(
        sources,
        {
            "account_identifier": [(0, "GB57TEST00000000009928", "GB57TEST00000000009928")],
            "destination_scheme": [(0, "IBAN", "IBAN")],
        },
    )
    install_response(monkeypatch, response(payload))
    evidence = extract_attempt(sources, settings=settings()).evidence
    case = CaseContract(baseline=baseline, sources=sources, evidence=evidence)
    reviewed = review_case(
        case, operator_id="SIMULATED_TEST_ONLY", destination_instructions_checked=True
    )
    result = complete_case(reviewed)
    assert result.comparison.state == "VERIFY"
    assert "DESTINATION_CHANGED" in result.comparison.reason_codes
    assert result.verification is None
