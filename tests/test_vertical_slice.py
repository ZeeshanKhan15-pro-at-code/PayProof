"""Capture-to-display integration; fixture demos and mocked structured HTTP only."""

import io
import json
import os
import secrets

import pytest
from pydantic import ValidationError

from payproof.cases import complete_case, review_case, start_case
from payproof.cli import main
from payproof.config import load_settings
from payproof.documents import capture_text
from payproof.fixtures import load_corpus
from payproof.presentation import render_evidence, render_result
from payproof.schemas import EVIDENCE_FIELDS, CaseContract

OLD_ACCOUNT = "GB46TEST00000000003821"
NEW_ACCOUNT = "GB57TEST00000000009928"
FORMATTED_NEW = "gb57 test 0000 0000 0099 28"


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch):
    for key in tuple(os.environ):
        if key.startswith("PAYPROOF_"):
            monkeypatch.delenv(key)

    def forbidden_network(*args, **kwargs):
        pytest.fail("vertical-slice test attempted real network access")

    monkeypatch.setattr("payproof.openai_extraction.build_opener", forbidden_network)


def seed():
    corpus = load_corpus()
    request = next(r for r in corpus.requests if r.fixture_id == "demo-account-change")
    vendor = next(v for v in corpus.vendors if v.revision_id == request.baseline_revision_id)
    return vendor, request


def files(tmp_path, email_text, invoice_text=None):
    vendor, _ = seed()
    record = tmp_path / "vendor.json"
    record.write_text(vendor.model_dump_json())
    email = tmp_path / "request.email.txt"
    email.write_text(email_text)
    args = [
        "analyze",
        "--vendor",
        str(record),
        "--email",
        str(email),
        "--operator",
        "test-reviewer",
    ]
    if invoice_text is not None:
        invoice = tmp_path / "invoice.txt"
        invoice.write_text(invoice_text)
        args += ["--invoice", str(invoice)]
    return args, record


def install_structured_http(monkeypatch, observations, *, failure=None):
    """Gold observations are independent of decisions; exercise the real HTTP adapter."""
    monkeypatch.setenv("PAYPROOF_EXTRACTION_MODE", "live")
    monkeypatch.setenv("PAYPROOF_PROVIDER_API_KEY", secrets.token_urlsafe(32))
    monkeypatch.setenv("PAYPROOF_PROVIDER_MODEL", "mock-extractor")
    calls = []

    class Opener:
        def open(self, request, *, timeout):
            body = json.loads(request.data)
            documents = json.loads(body["input"][0]["content"])["documents"]
            calls.append(documents)
            assert body["text"]["format"]["strict"] is True
            assert body["tools"] == [] and body["store"] is False
            assert "baseline" not in body and "trusted_vendor" not in body
            if failure == "TIMEOUT":
                raise TimeoutError
            payload = {name: {"status": "MISSING", "candidates": []} for name in EVIDENCE_FIELDS}
            for name, values in observations.items():
                payload[name] = {
                    "status": "FOUND" if len(values) == 1 else "AMBIGUOUS",
                    "candidates": [
                        {
                            "value": raw,
                            "raw_text": raw,
                            "source_id": documents[index]["source_id"],
                            "exact_excerpt": documents[index]["text"],
                        }
                        for index, raw in values
                    ],
                }
            if failure == "INVALID_RESPONSE":
                payload["state"] = "VERIFIED"
            if failure == "EVIDENCE_INVALID":
                payload["account_identifier"]["candidates"][0]["exact_excerpt"] = "invented quote"
            response = {
                "status": "completed",
                "model": "mock-extractor",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": json.dumps(payload)}],
                    }
                ],
            }
            return io.BytesIO(json.dumps(response).encode())

    monkeypatch.setattr("payproof.openai_extraction.build_opener", lambda *args: Opener())
    return calls


def test_seeded_capture_extraction_review_comparison_and_exact_source_binding():
    vendor, request = seed()
    source = capture_text(
        request.source.text, operator_id="test-reviewer", kind="EMAIL", label="demo"
    )
    case = start_case(
        vendor, (source,), settings=load_settings({"PAYPROOF_EXTRACTION_MODE": "fixture"})
    )
    assert case.review is None and case.comparison is None
    assert case.evidence.extraction.method == "FIXTURE"
    assert case.evidence.request_id != request.evidence.request_id
    assert case.sources[0].source_id != request.source.source_id
    unreviewed = complete_case(case)
    assert unreviewed.comparison.state == "UNCERTAIN"
    assert unreviewed.comparison.reason_codes == ("REVIEW_REQUIRED",)
    reviewed = review_case(case, operator_id="test-reviewer", destination_instructions_checked=True)
    completed = complete_case(reviewed)
    assert completed.comparison.state == "VERIFY"
    assert completed.comparison.reason_codes == ("DESTINATION_CHANGED",)
    assert completed.baseline.payment_identity.account_identifier == OLD_ACCOUNT
    assert completed.comparison.requested_identity.account_identifier == NEW_ACCOUNT
    assert completed.verification is None
    assert set(completed.review.reviewed_evidence_ids) == {
        s.evidence_id for s in completed.evidence.spans()
    }
    span = completed.evidence.account_identifier.candidates[0].evidence
    assert span.source_id == source.source_id
    assert source.text[span.location.char_start : span.location.char_end] == span.exact_excerpt
    assert span.exact_excerpt == f"Please pay this invoice to IBAN {NEW_ACCOUNT}."
    assert vendor == completed.baseline  # Neither extraction nor review learns a baseline.
    assert CaseContract.model_validate_json(completed.model_dump_json()) == completed
    assert case.review is None and case.comparison is None
    assert unreviewed.comparison.state == "UNCERTAIN"  # Earlier result remains unchanged.


def test_cli_seeded_demo_shows_changed_values_both_sources_and_required_verification(
    monkeypatch, capsys
):
    displayed_before_acknowledgement = []

    def acknowledge(prompt):
        preview = capsys.readouterr().out
        displayed_before_acknowledgement.append(preview)
        assert OLD_ACCOUNT in preview and NEW_ACCOUNT in preview
        assert "synthetic-onboarding/demo-account-3821" in preview
        assert f'Exact excerpt: "Please pay this invoice to IBAN {NEW_ACCOUNT}."' in preview
        assert "Check all original source text and evidence" in prompt
        return "REVIEWED"

    monkeypatch.setattr("builtins.input", acknowledge)
    assert main(["demo", "--operator", "human-demo-reviewer"]) == 0
    output = capsys.readouterr().out
    assert len(displayed_before_acknowledgement) == 1
    assert "STATE: VERIFY" in output
    assert "Reason codes: DESTINATION_CHANGED" in output
    assert (
        f'account_identifier: CHANGED | trusted "{OLD_ACCOUNT}" -> requested "{NEW_ACCOUNT}"'
        in output
    )
    assert "requires independent human verification" in output
    assert "human-demo-reviewer" in output
    assert "previously trusted callback" in output and "+1-202-555-0182" in output
    assert "No independent-verification or account-ownership record was created." in output


def test_demo_smoke_is_explicitly_simulated_and_ignores_live_environment(monkeypatch, capsys):
    monkeypatch.setenv("PAYPROOF_EXTRACTION_MODE", "live")
    monkeypatch.setenv("PAYPROOF_PROVIDER_API_KEY", secrets.token_urlsafe(32))
    assert main(["demo", "--simulate-review"]) == 0
    output = capsys.readouterr().out
    assert "STATE: VERIFY" in output and "EXTRACTION: FIXTURE" in output
    assert "SIMULATED SOURCE REVIEW" in output and "synthetic-demo-review-simulation" in output
    assert "Trusted account ending: 3821" in output
    assert "Requested account ending: 9928" in output
    assert os.environ["PAYPROOF_PROVIDER_API_KEY"] not in output


@pytest.mark.parametrize("answer", ["", "yes", "VERIFIED", "UNCERTAIN", "reviewed"])
def test_review_is_an_explicit_action_and_not_a_verdict_submission(answer, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    assert main(["demo"]) == 2
    output = capsys.readouterr().out
    assert "STATE: UNCERTAIN" in output and "REVIEW_REQUIRED" in output
    assert "Source review: not recorded." in output


@pytest.mark.parametrize("no_review", [False, True])
def test_eof_and_no_review_flag_leave_demo_unresolved(no_review, monkeypatch, capsys):
    def end_of_input(prompt):
        if no_review:
            pytest.fail("--no-review unexpectedly prompted")
        raise EOFError

    monkeypatch.setattr("builtins.input", end_of_input)
    assert main(["demo"] + (["--no-review"] if no_review else [])) == 2
    assert "STATE: UNCERTAIN" in capsys.readouterr().out


@pytest.mark.parametrize(
    "fixture_id,state",
    [
        ("unchanged", "UNCHANGED"),
        ("unsupported-country", "UNCERTAIN"),
        ("unicode-identifier", "UNCERTAIN"),
    ],
)
def test_cli_fixture_path_demonstrates_other_outcomes(
    tmp_path, fixture_id, state, monkeypatch, capsys
):
    corpus = load_corpus()
    request = next(r for r in corpus.requests if r.fixture_id == fixture_id)
    vendor = next(v for v in corpus.vendors if v.revision_id == request.baseline_revision_id)
    record = tmp_path / "vendor.json"
    record.write_text(vendor.model_dump_json())
    source = tmp_path / "request.txt"
    source.write_text(request.source.text)
    option = {"EMAIL": "--email", "INVOICE": "--invoice"}.get(request.source.kind, "--text")
    monkeypatch.setenv("PAYPROOF_EXTRACTION_MODE", "fixture")
    monkeypatch.setattr("builtins.input", lambda prompt: "REVIEWED")
    assert main(["analyze", "--vendor", str(record), option, str(source)]) == (
        2 if state == "UNCERTAIN" else 0
    )
    output = capsys.readouterr().out
    assert f"STATE: {state}" in output
    assert f"Reason codes: {', '.join(request.expected_reason_codes)}" in output


@pytest.mark.parametrize(
    "accounts,state,reason",
    [
        (NEW_ACCOUNT, "VERIFY", "DESTINATION_CHANGED"),
        (OLD_ACCOUNT, "UNCHANGED", "DESTINATION_MATCH"),
    ],
)
def test_cli_email_invoice_pair_from_structured_http(
    accounts, state, reason, tmp_path, monkeypatch, capsys
):
    formatted = FORMATTED_NEW if accounts == NEW_ACCOUNT else OLD_ACCOUNT.lower()
    args, _ = files(
        tmp_path,
        f"Email instruction: pay IBAN {accounts}.",
        f"Invoice instruction: pay IBAN {formatted}.",
    )
    calls = install_structured_http(
        monkeypatch,
        {
            "account_identifier": [(0, accounts), (1, formatted)],
            "destination_scheme": [(0, "IBAN"), (1, "IBAN")],
        },
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "REVIEWED")
    assert main(args) == 0
    assert len(calls) == 1 and [d["kind"] for d in calls[0]] == ["EMAIL", "INVOICE"]
    output = capsys.readouterr().out
    assert f"STATE: {state}" in output and f"Reason codes: {reason}" in output
    assert "EXTRACTION: AI" in output and "account_identifier: AMBIGUOUS" in output
    assert "request.email.txt" in output and "invoice.txt" in output
    assert f'Exact excerpt: "Email instruction: pay IBAN {accounts}."' in output
    assert f'Exact excerpt: "Invoice instruction: pay IBAN {formatted}."' in output


def test_cli_conflicting_pair_remains_uncertain_after_explicit_review(
    tmp_path, monkeypatch, capsys
):
    args, _ = files(tmp_path, f"Email: pay {NEW_ACCOUNT}.", f"Invoice: pay {OLD_ACCOUNT}.")
    install_structured_http(
        monkeypatch, {"account_identifier": [(0, NEW_ACCOUNT), (1, OLD_ACCOUNT)]}
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "REVIEWED")
    assert main(args) == 2
    output = capsys.readouterr().out
    assert "STATE: UNCERTAIN" in output and "Reason codes: DESTINATION_AMBIGUOUS" in output
    assert "Contradiction account_identifier" in output
    assert "request.email.txt" in output and "invoice.txt" in output


def test_cli_missing_payment_details_remain_uncertain_after_review(tmp_path, monkeypatch, capsys):
    args, _ = files(tmp_path, "Please pay invoice DEMO-002. Payment details will follow.")
    install_structured_http(monkeypatch, {})
    monkeypatch.setattr("builtins.input", lambda prompt: "REVIEWED")
    assert main(args) == 2
    output = capsys.readouterr().out
    assert "STATE: UNCERTAIN" in output and "Reason codes: DESTINATION_MISSING" in output
    assert "account_identifier: MISSING" in output
    assert "Missing REQUEST.account_identifier" in output


@pytest.mark.parametrize(
    "failure,reason",
    [
        ("TIMEOUT", "EXTRACTION_FAILED"),
        ("INVALID_RESPONSE", "EXTRACTION_FAILED"),
        ("EVIDENCE_INVALID", "EVIDENCE_INVALID"),
    ],
)
def test_provider_failure_cannot_be_bypassed_by_source_review(
    failure, reason, tmp_path, monkeypatch, capsys
):
    args, _ = files(tmp_path, f"Pay {NEW_ACCOUNT}.")
    install_structured_http(
        monkeypatch, {"account_identifier": [(0, NEW_ACCOUNT)]}, failure=failure
    )
    monkeypatch.setattr(
        "builtins.input", lambda prompt: pytest.fail("failed extraction prompted for review")
    )
    assert main(args) == 2
    output = capsys.readouterr().out
    assert "STATE: UNCERTAIN" in output and f"Reason codes: {reason}" in output
    assert "Source review: not recorded." in output
    assert "account_identifier: UNREADABLE" in output


@pytest.mark.parametrize("mode", ["disabled", "fixture"])
def test_unconfigured_or_unrecognized_fixture_input_is_not_guessed(
    mode, tmp_path, monkeypatch, capsys
):
    args, _ = files(tmp_path, f"Not a bundled source. Pay {NEW_ACCOUNT}.")
    monkeypatch.setenv("PAYPROOF_EXTRACTION_MODE", mode)
    monkeypatch.setattr(
        "builtins.input", lambda prompt: pytest.fail("unconfigured extraction prompted")
    )
    assert main(args) == 2
    assert "Reason codes: EXTRACTION_FAILED" in capsys.readouterr().out


@pytest.mark.parametrize("invalid_baseline", ["malformed", "newer-than-request"])
def test_invalid_baseline_is_rejected_before_provider_use(
    invalid_baseline, tmp_path, monkeypatch, capsys
):
    args, record = files(tmp_path, f"Pay {NEW_ACCOUNT}.")
    data = json.loads(record.read_text())
    if invalid_baseline == "malformed":
        data["state"] = "VERIFIED"
    else:
        data["last_verified_at"] = "2027-01-01T08:00:00Z"
    record.write_text(json.dumps(data))
    calls = install_structured_http(monkeypatch, {"account_identifier": [(0, NEW_ACCOUNT)]})
    assert main(args) == 1
    assert calls == []
    captured = capsys.readouterr()
    assert "STATE:" not in captured.out and "Operation failed" in captured.err


@pytest.mark.parametrize("source_text", ["", "X" * 20_001, "X" * 80_001])
def test_invalid_document_limits_fail_before_extraction(source_text, tmp_path, monkeypatch, capsys):
    args, _ = files(tmp_path, source_text)
    calls = install_structured_http(monkeypatch, {})
    assert main(args) == 1 and calls == []
    assert "STATE:" not in capsys.readouterr().out


def test_control_characters_and_unicode_formatting_are_escaped_in_display(
    tmp_path, monkeypatch, capsys
):
    text = f"Untrusted \x1b[2J \u202e instruction. Pay {NEW_ACCOUNT}."
    args, _ = files(tmp_path, text)
    install_structured_http(monkeypatch, {"account_identifier": [(0, NEW_ACCOUNT)]})
    monkeypatch.setattr("builtins.input", lambda prompt: "REVIEWED")
    assert main(args) == 0
    output = capsys.readouterr().out
    assert "\x1b" not in output and "\u202e" not in output
    assert "\\u001b" in output and "\\u202e" in output
    assert "STATE: VERIFY" in output


def test_simulated_review_is_impossible_for_arbitrary_real_input():
    with pytest.raises(SystemExit) as stopped:
        main(["analyze", "--vendor", "unused.json", "--email", "unused.txt", "--simulate-review"])
    assert stopped.value.code == 2


@pytest.mark.parametrize("acknowledgement", [False, "true", 1])
def test_case_service_requires_an_explicit_boolean_acknowledgement(acknowledgement):
    vendor, request = seed()
    source = capture_text(request.source.text, operator_id="test", kind="EMAIL")
    case = start_case(
        vendor, (source,), settings=load_settings({"PAYPROOF_EXTRACTION_MODE": "fixture"})
    )
    with pytest.raises(ValueError, match="explicit acknowledgement"):
        review_case(case, operator_id="test", destination_instructions_checked=acknowledgement)


def test_case_service_rejects_failed_extraction_review_and_copied_invalid_source():
    vendor, request = seed()
    source = capture_text(request.source.text, operator_id="test", kind="EMAIL")
    failed = start_case(vendor, (source,), settings=load_settings({}))
    with pytest.raises(ValueError, match="failed extraction"):
        review_case(failed, operator_id="test", destination_instructions_checked=True)
    valid = start_case(
        vendor, (source,), settings=load_settings({"PAYPROOF_EXTRACTION_MODE": "fixture"})
    )
    invalid_source = source.model_copy(update={"sha256": "0" * 64})
    with pytest.raises(ValidationError):
        review_case(
            valid.model_copy(update={"sources": (invalid_source,)}),
            operator_id="test",
            destination_instructions_checked=True,
        )


def test_result_display_links_both_value_sources_and_preserves_absence():
    vendor, request = seed()
    source = capture_text(request.source.text, operator_id="test", kind="EMAIL")
    case = start_case(
        vendor, (source,), settings=load_settings({"PAYPROOF_EXTRACTION_MODE": "fixture"})
    )
    case = complete_case(
        review_case(case, operator_id="test", destination_instructions_checked=True)
    )
    display = render_evidence(case) + "\n" + render_result(case)
    assert "Old value source: SYNTHETIC_FIXTURE" in display and "New value source: EMAIL" in display
    assert "routing_identifier: MISSING" in display
    assert "routing_identifier: UNKNOWN | trusted null -> requested null" in display
    assert "STATE: VERIFIED" not in display and "STATE: SAFE" not in display
