"""Server-rendered safety presentation over real persisted synthetic workflows."""

from html import escape
from uuid import uuid4

import pytest
from test_operator_web import current, demo_case, login, step, verify_data
from test_operator_web import web as web

from payproof.demo_proof import load_demo, prepared_inputs
from payproof.schemas import TrustedVendorRecord
from payproof.storage import SQLiteStore, WorkflowError

HEADLINES = {
    "VERIFY": "PAYMENT DESTINATION CHANGED",
    "UNCHANGED": "NO SUPPORTED PAYMENT DESTINATION CHANGE DETECTED",
    "UNCERTAIN": "PAYPROOF CANNOT RELIABLY COMPARE THIS REQUEST YET",
}


@pytest.mark.parametrize("index", range(5))
def test_result_leads_with_actual_state_and_preserves_competing_source_context(web, index):
    bundle = load_demo()
    item = bundle.cases[index]
    db = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    try:
        db.put_vendor(bundle.vendor, operator_id="synthetic-setup")
        case = db.create_case(
            prepared_inputs(item), bundle.vendor.vendor_id, operator_id="synthetic-setup"
        )
    finally:
        db.close()
    client = login(web)
    if index != 3:
        assert step(web, case.case_id, "review", {"source_review": "yes"}).status_code == 302
    assert step(web, case.case_id, "compare").status_code == 302
    stored = current(web, case.case_id)
    result = stored.snapshot.comparison
    assert result.state == item.expected_state
    page = client.get(f"/operator/cases/{case.case_id}").text
    headline = HEADLINES[result.state]
    assert page.index(headline) < page.index('id="original-sources"')
    for reason in result.reason_codes:
        assert reason in page
    assert "DEMO EXAMPLE" in page if index != 3 else "EXTRACTION NOT COMPLETED" in page
    assert "OUTSIDE PAYPROOF" in page
    assert "ORIGINAL SOURCE" in page and "DETERMINISTIC COMPARISON" in page
    for source in stored.snapshot.sources:
        assert escape(source.text, quote=False) in page
    if result.state == "UNCHANGED":
        assert (
            headline + '</h2><p class="hero-lead">This does not authorize payment or prove' in page
        )
    if result.state == "VERIFY":
        assert "••••3821" in page and "••••9928" in page
        assert "Do not use contact information supplied only by the new request." in page
        assert bundle.vendor.callback_contact.value in page
        assert 'name="independently_checked"' in page
    elif result.state == "UNCERTAIN":
        assert 'name="independently_checked"' not in page
    if index == 4:
        # An omitted current account must remain visible next to the old AI/fixture observation.
        spotlight = page.split('class="evidence-spotlight"', 1)[1].split('class="provenance-flow"')[
            0
        ]
        assert "NOT OBSERVED BY EXTRACTION" in spotlight
        assert "GB46TEST00000000003821" in spotlight
        assert "GB57TEST00000000009928" in spotlight
        assert "DESTINATION_AMBIGUOUS" in page


def receipt_url(web, case_id):
    db = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    try:
        event = db.verification_events(case_id)[0]
    finally:
        db.close()
    return f"/operator/cases/{case_id}/receipts/{event.event_id}", event


@pytest.mark.parametrize("outcome", ["CONFIRMED", "NOT_CONFIRMED", "INCONCLUSIVE"])
def test_receipt_preserves_recorded_evidence_outcome_and_print_controls(web, outcome):
    client, case_id = demo_case(web)
    step(web, case_id, "review", {"source_review": "yes"})
    step(web, case_id, "compare")
    compared = current(web, case_id)
    assert step(web, case_id, "verify", verify_data() | {"outcome": outcome}).status_code == 302
    url, event = receipt_url(web, case_id)
    receipt = client.get(url).json
    assert receipt["current"]
    assert receipt["recorded_comparison_state"] == "VERIFY"
    assert receipt["case_revision_id"] == str(compared.revision_id)
    assert receipt["case_version"] == compared.version
    assert receipt["snapshot"] == compared.snapshot.model_dump(mode="json")
    assert receipt["event"]["outcome"] == outcome
    response = client.get(url, headers={"Accept": "text/html"})
    assert response.status_code == 200
    page = response.text
    assert "Verification Receipt" in page and "DEMO EXAMPLE · SYNTHETIC" in page
    assert "••••3821" in page and "••••9928" in page
    assert outcome in page and "DESTINATION_CHANGED" in page
    assert "NOT_PROVIDED" in page and "NOT_ESTABLISHED" in page
    assert "does not establish bank ownership, legitimacy, fraud or payment approval" in page
    assert 'id="print-receipt"' in page and 'src="/static/receipt.js"' in page
    assert "onclick" not in page
    for source in compared.snapshot.sources:
        assert str(source.source_id) in page and source.sha256 in page
    for span in compared.snapshot.evidence.spans():
        assert str(span.evidence_id) in page and escape(span.exact_excerpt, quote=False) in page
    assert str(event.baseline_revision_id) in page
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert (
        "script-src"
        not in client.get(f"/operator/cases/{case_id}").headers["Content-Security-Policy"]
    )
    assert client.get("/static/receipt.js").status_code == 200
    assert "@media print" in client.get("/static/operator.css").text


def test_stale_receipt_never_substitutes_new_trusted_record_or_fresh_comparison(web):
    client, case_id = demo_case(web)
    step(web, case_id, "review", {"source_review": "yes"})
    step(web, case_id, "compare")
    compared = current(web, case_id)
    step(web, case_id, "verify", verify_data())
    url, _ = receipt_url(web, case_id)
    db = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    try:
        prior = db.get_vendor(compared.selected_vendor_id)
        identity = compared.snapshot.comparison.requested_identity
        updated = TrustedVendorRecord.model_validate(
            prior.model_dump()
            | {
                "revision_id": uuid4(),
                "canonical_vendor_name": "New revised synthetic vendor",
                "payment_identity": identity,
            }
        )
        db.put_vendor(
            updated, operator_id="synthetic-human", expected_revision_id=prior.revision_id
        )
    finally:
        db.close()
    page = client.get(f"/operator/cases/{case_id}").text
    assert "THIS RESULT IS HISTORICAL" in page
    assert 'name="independently_checked"' not in page
    assert step(web, case_id, "refresh").status_code == 302
    step(web, case_id, "review", {"source_review": "yes"})
    step(web, case_id, "compare")
    assert current(web, case_id).snapshot.comparison.state == "UNCHANGED"
    receipt = client.get(url).json
    assert receipt["current"] is False and receipt["comparison_state"] is None
    assert receipt["recorded_comparison_state"] == "VERIFY"
    assert receipt["snapshot"] == compared.snapshot.model_dump(mode="json")
    html = client.get(url, headers={"Accept": "text/html"}).text
    assert "HISTORICAL — NOT CURRENT" in html and "VERIFY · recorded comparison" in html
    assert "New revised synthetic vendor" not in html
    assert "••••3821" in html and "••••9928" in html


def test_receipt_rejects_mismatched_recorded_comparison(web, monkeypatch):
    _, case_id = demo_case(web)
    step(web, case_id, "review", {"source_review": "yes"})
    step(web, case_id, "compare")
    step(web, case_id, "verify", verify_data())
    _, event = receipt_url(web, case_id)
    db = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    original_get_case = db.get_case

    def mismatched(case_id, revision_id=None):
        record = original_get_case(case_id, revision_id)
        if revision_id == event.source_revision_id:
            comparison = record.snapshot.comparison.model_copy(update={"comparison_id": uuid4()})
            snapshot = record.snapshot.model_copy(update={"comparison": comparison})
            return record.model_copy(update={"snapshot": snapshot})
        return record

    monkeypatch.setattr(db, "get_case", mismatched)
    try:
        with pytest.raises(WorkflowError, match="recorded comparison"):
            db.verification_receipt(case_id, event.event_id)
    finally:
        db.close()
