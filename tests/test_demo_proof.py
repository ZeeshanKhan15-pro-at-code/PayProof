"""Presentation uses saved evidence, not invented live accuracy or human actions."""

import json
from pathlib import Path

import pytest
from test_operator_web import current, login, step, verify_data

from payproof.config import load_settings
from payproof.demo_proof import load_demo, main, run_demo, seed_demo
from payproof.schemas import CaseContract
from payproof.storage import SQLiteStore
from payproof.validation import parse_contract
from payproof.web import create_app

GOLD = Path("benchmarks/phase2-redteam/after-gold/report.json")
LIVE = Path("benchmarks/phase2-redteam/live-attempt.json")


def test_demo_proves_five_paths_without_creating_human_confirmation():
    bundle = load_demo()
    assert bundle.vendor.canonical_vendor_name == "Acme Supplies (synthetic)"
    outcomes = run_demo(bundle)
    assert [c.comparison.state for c in outcomes] == [
        "VERIFY",
        "UNCHANGED",
        "UNCERTAIN",
        "UNCERTAIN",
        "UNCERTAIN",
    ]
    assert outcomes[0].comparison.reason_codes == ("DESTINATION_CHANGED",)
    assert outcomes[0].baseline.payment_identity.account_identifier.endswith("3821")
    assert outcomes[0].comparison.requested_identity.account_identifier.endswith("9928")
    assert all(c.verification is None for c in outcomes)
    assert outcomes[3].evidence.extraction.failure_code == "NOT_CONFIGURED"
    assert outcomes[3].review is None
    assert "DESTINATION_AMBIGUOUS" in outcomes[4].comparison.reason_codes
    assert len(outcomes[4].evidence.account_identifier.candidates) == 1
    for case in outcomes:
        parse_contract(CaseContract, case.model_dump_json())
        for span in case.evidence.spans():
            source = next(s for s in case.sources if s.source_id == span.source_id)
            assert (
                source.text[span.location.char_start : span.location.char_end] == span.exact_excerpt
            )


def test_report_numbers_are_saved_artifact_values_and_preserve_failures(tmp_path):
    output = tmp_path / "proof"
    assert main(["--output", str(output), "--gold", str(GOLD), "--live-status", str(LIVE)]) == 0
    saved = json.loads((output / "proof.json").read_text())
    original = json.loads(GOLD.read_text())
    assert saved["gold"] == original
    assert saved["live_status"] == json.loads(LIVE.read_text())
    page = (output / "report.html").read_text()
    assert "56/72" in page and "53/72" in page
    assert "30/33" in page and "12/24" in page
    assert "FAIL" in page and "PENDING" in page
    assert "Live extraction: BLOCKED / NOT_CONFIGURED" in page
    assert "Live end-to-end: NOT_MEASURED" in page
    assert "NOT OBSERVED BY EXTRACTION" in page
    assert "Acme Supplies" in page and "+1-202-555-0182" in page
    assert "PP-17" in page and "PP-60" in page
    assert main(["--output", str(output)]) == 2  # Preserve the first run.


def test_missing_artifact_never_falls_back_to_invented_metrics(tmp_path):
    assert main(["--output", str(tmp_path / "proof"), "--gold", str(tmp_path / "absent")]) == 2
    assert not (tmp_path / "proof").exists()


def test_seeding_preserves_explicit_human_steps_and_refuses_existing_database(tmp_path):
    directory = tmp_path / "operator"
    case_ids = seed_demo(load_demo(), directory)
    store = SQLiteStore(directory / "payproof.sqlite3")
    try:
        for case_id in case_ids:
            case = store.get_case(case_id)
            assert case.snapshot.review is None
            assert case.snapshot.comparison is None
            assert case.independent_verification_status == "NOT_VERIFIED"
            assert not store.verification_events(case_id)
    finally:
        store.close()
    with pytest.raises(FileExistsError):
        seed_demo(load_demo(), directory)


def test_inconsistent_saved_counts_are_rejected_before_report_creation(tmp_path):
    bad = json.loads(GOLD.read_text())
    bad["tracks"][0]["metrics"]["correct_state_classifications"] += 1
    path = tmp_path / "inconsistent.json"
    path.write_text(json.dumps(bad))
    assert main(["--output", str(tmp_path / "proof"), "--gold", str(path)]) == 2
    assert not (tmp_path / "proof").exists()


@pytest.mark.parametrize("index", range(5))
def test_acme_operator_proof_keeps_review_comparison_and_human_action_separate(tmp_path, index):
    import secrets

    bundle = load_demo()
    seed_demo(bundle, tmp_path / "operator")
    token = secrets.token_urlsafe(40)
    settings = load_settings(
        {
            "PAYPROOF_ENV": "test",
            "PAYPROOF_DATA_DIR": str(tmp_path / "operator"),
            "PAYPROOF_SECRET_KEY": secrets.token_urlsafe(40),
            "PAYPROOF_OPERATOR_TOKEN": token,
        }
    )
    app = create_app(settings)
    web = app, app.test_client(), settings, token
    client = login(web)
    case_id = bundle.cases[index].inputs.evidence.request_id
    page = client.get(f"/operator/cases/{case_id}")
    assert page.status_code == 200
    assert "Acme Supplies" in client.get("/operator").text
    assert "Human attestation: NOT_VERIFIED" in page.text
    if index == 3:
        assert step(web, case_id, "review", {"source_review": "yes"}).status_code == 400
    else:
        assert step(web, case_id, "review", {"source_review": "yes"}).status_code == 302
    assert step(web, case_id, "compare").status_code == 302
    stored = current(web, case_id)
    assert stored.snapshot.comparison.state == bundle.cases[index].expected_state
    page = client.get(f"/operator/cases/{case_id}").text
    if index == 4:
        assert "NOT OBSERVED BY EXTRACTION" in page
        assert "GB57TEST00000000009928" in page
    if index == 0:
        assert "DESTINATION_CHANGED" in page and "+1-202-555-0182" in page
        assert "synthetic-onboarding/acme-proof-3821" in page
        assert step(web, case_id, "verify", verify_data()).status_code == 302
        confirmed = current(web, case_id)
        assert confirmed.independent_verification_status == "VERIFIED"
        assert confirmed.snapshot.comparison.state == "VERIFY"
    elif index >= 2:
        assert 'name="independently_checked"' not in page
        assert step(web, case_id, "verify", verify_data()).status_code == 409
        assert current(web, case_id).snapshot.verification is None
