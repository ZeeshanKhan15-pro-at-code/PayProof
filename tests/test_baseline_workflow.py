"""Real Flask/SQLite lifecycle; provider calls are explicitly mocked where used."""

import io
import json
import secrets
import sqlite3
from importlib.resources import files
from uuid import UUID, uuid4

import pytest
from test_extraction import wire_payload
from test_operator_web import current, login, post, step, verify_data
from test_operator_web import web as web

from payproof.config import load_settings
from payproof.openai_extraction import ProviderCompletion, ProviderFailure
from payproof.storage import SQLiteStore
from payproof.web import create_app

OLD = "GB46TEST00000000003821"
NEW = "GB57TEST00000000009928"


def new_draft(web, extra=None, url="/operator/baselines/new"):
    client = web[1]
    data = {
        "name": "Prior synthetic Acme",
        "source_reference": "independent prior record",
        "description": "Known instructions established previously",
        "verified_at": "2026-10-01T08:00:00Z",
        "account": OLD,
        "submission_id": str(uuid4()),
    } | (extra or {})
    response = post(client, url, data)
    assert response.status_code == 302, response.text
    return UUID(response.location.rsplit("/", 1)[1]), data


def assertion():
    return {
        "source_reviewed": "yes",
        "previously_trusted": "yes",
        "contact_independently_established": "yes",
        "contact_method": "PHONE",
        "contact": "+1-202-555-0144",
    }


def vendor(web):
    with_store = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    try:
        return with_store.list_vendors()[0]
    finally:
        with_store.close()


def current_case(web, vendor_id, submission=None):
    from payproof.fixtures import load_corpus

    seed = next(r for r in load_corpus().requests if r.fixture_id == "demo-account-change")
    data = {
        "vendor_id": str(vendor_id),
        "email": seed.source.text,
        "submission_id": str(submission or uuid4()),
    }
    response = post(web[1], "/operator/cases/new", data)
    assert response.status_code == 302, response.text
    return UUID(response.location.rsplit("/", 1)[1]), data


def test_manual_baseline_through_current_request_receipt_and_revision(web):
    client = login(web)
    assert client.get("/readyz").status_code == 200
    draft_id, data = new_draft(web)
    db = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    assert db.list_vendors() == ()
    assert db.get_baseline_draft(draft_id).manual_account == OLD
    db.close()
    page = client.get(f"/operator/baselines/{draft_id}")
    assert OLD in page.text and "no trust conferred" in page.text
    assert (
        post(
            client, f"/operator/baselines/{draft_id}", assertion() | {"previously_trusted": "no"}
        ).status_code
        == 400
    )
    assert post(client, f"/operator/baselines/{draft_id}", assertion()).status_code == 302
    baseline = vendor(web)
    assert baseline.payment_identity.account_identifier == OLD
    assert baseline.callback_contact.value == assertion()["contact"]
    assert post(client, f"/operator/baselines/{draft_id}", assertion()).status_code == 302
    assert (
        post(
            client,
            f"/operator/baselines/{draft_id}",
            assertion() | {"contact": "suspect@example.test"},
        ).status_code
        == 409
    )
    repeated = post(client, "/operator/baselines/new", data)
    assert repeated.location.endswith(str(draft_id))
    case_id, case_data = current_case(web, baseline.vendor_id)
    assert post(client, "/operator/cases/new", case_data).location.endswith(str(case_id))
    assert (
        post(client, "/operator/cases/new", case_data | {"email": "different"}).status_code == 409
    )
    assert step(web, case_id, "verify", verify_data()).status_code == 409
    assert step(web, case_id, "review", {"source_review": "yes"}).status_code == 302
    assert step(web, case_id, "compare").status_code == 302
    assert current(web, case_id).snapshot.comparison.state == "VERIFY"
    request_revision = str(current(web, case_id).revision_id)
    action = verify_data()
    assert step(web, case_id, "verify", action).status_code == 302
    assert (
        post(
            client, f"/operator/cases/{case_id}/verify", action | {"revision_id": request_revision}
        ).status_code
        == 302
    )
    db = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    events = db.verification_events(case_id)
    assert len(events) == 1
    assert len(db.list_cases()) == 1
    assert db.db.execute("SELECT count(*) FROM baseline_assertions").fetchone()[0] == 1
    db.close()
    url = f"/operator/cases/{case_id}/receipts/{events[0].event_id}"
    receipt = client.get(url).json
    assert receipt["current"] and receipt["comparison_state"] == "VERIFY"
    assert receipt["event"]["trusted_contact"]["value"] == assertion()["contact"]
    assert receipt["payment_authorization"] == "NOT_PROVIDED"
    revise_url = f"/operator/baselines/new?vendor_id={baseline.vendor_id}"
    revised, _ = new_draft(
        web, {"account": NEW, "expected_revision_id": str(baseline.revision_id)}, revise_url
    )
    assert post(client, f"/operator/baselines/{revised}", assertion()).status_code == 302
    assert current(web, case_id).stale
    assert client.get(url).json["status"] == "HISTORICAL_STALE"
    assert step(web, case_id, "verify", verify_data()).status_code == 409
    assert step(web, case_id, "refresh").status_code == 302
    assert current(web, case_id).snapshot.review is None
    assert step(web, case_id, "review", {"source_review": "yes"}).status_code == 302
    assert step(web, case_id, "compare").status_code == 302
    assert current(web, case_id).snapshot.comparison.state == "UNCHANGED"
    restarted = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    assert len(restarted.case_history(case_id)) == 7
    assert restarted.get_baseline_draft(draft_id).manual_account == OLD
    restarted.close()


def live_web(web, monkeypatch, mode="success"):
    settings = load_settings(
        {
            "PAYPROOF_ENV": "test",
            "PAYPROOF_DATA_DIR": str(web[2].data_dir),
            "PAYPROOF_SECRET_KEY": secrets.token_urlsafe(48),
            "PAYPROOF_OPERATOR_TOKEN": web[3],
            "PAYPROOF_EXTRACTION_MODE": "live",
            "PAYPROOF_PROVIDER": "featherless",
            "PAYPROOF_PROVIDER_MODEL": "synthetic-model",
            "PAYPROOF_PROVIDER_API_KEY": secrets.token_urlsafe(32),
        }
    )

    def complete(provider, sources):
        if mode == "timeout":
            raise ProviderFailure("TIMEOUT")
        payload = wire_payload(
            sources,
            {"account_identifier": [(0, OLD, OLD)], "destination_scheme": [(0, "IBAN", "IBAN")]},
        )
        if mode == "fabricated":
            payload["account_identifier"]["candidates"][0]["exact_excerpt"] = "fabricated"
        raw = json.dumps(payload).encode()
        return ProviderCompletion(text=raw.decode(), model="synthetic-model", raw_response=raw)

    monkeypatch.setattr("payproof.providers.FeatherlessExtractionProvider.complete", complete)
    app = create_app(settings)
    return app, app.test_client(), settings, web[3]


@pytest.mark.parametrize("upload", [False, True])
def test_previous_evidence_captured_extracted_then_explicitly_trusted(web, monkeypatch, upload):
    web = live_web(web, monkeypatch)
    client = login(web)
    text = f"Previous invoice instructions: Pay to IBAN {OLD}."
    # An ordinary prior invoice, not a text that declares a destination obsolete.
    text = f"Invoice payment instructions: Pay to IBAN {OLD}."
    extra = {"account": "", "upload_kind": "INVOICE"}
    extra |= {"upload": (io.BytesIO(text.encode()), "prior.eml")} if upload else {"invoice": text}
    draft_id, _ = new_draft(web, extra)
    assert post(client, f"/operator/baselines/{draft_id}", assertion()).status_code == 302
    db = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    draft = db.get_baseline_draft(draft_id)
    assert draft.inputs.sources[0].text == text
    assert draft.inputs.evidence.extraction.method == "AI"
    assert draft.inputs.evidence.spans()[0].exact_excerpt == text
    assert db.db.execute("SELECT count(*) FROM sources").fetchone()[0] == 1
    assert db.db.execute("SELECT count(*) FROM extraction_attempts").fetchone()[0] == 1
    assert db.list_vendors()[0].provenance.recorded_by == "synthetic-human"
    db.close()


@pytest.mark.parametrize(
    "mode,text",
    [
        ("timeout", f"Pay to IBAN {OLD}."),
        ("fabricated", f"Pay to IBAN {OLD}."),
        ("success", f"Old IBAN {OLD}; current IBAN {NEW}."),
    ],
)
def test_failed_or_competing_baseline_cannot_be_trusted(web, monkeypatch, mode, text):
    web = live_web(web, monkeypatch, mode)
    client = login(web)
    draft_id, _ = new_draft(web, {"account": "", "invoice": text})
    page = client.get(f"/operator/baselines/{draft_id}")
    assert "unresolved" in page.text
    assert post(client, f"/operator/baselines/{draft_id}", assertion()).status_code == 400
    db = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    assert db.list_vendors() == ()
    db.close()


def test_migration_v1_restart_and_unconfigured_readiness(tmp_path):
    path = tmp_path / "payproof.sqlite3"
    old = sqlite3.connect(path)
    old.executescript(files("payproof").joinpath("migrations/001_initial.sql").read_text())
    old.close()
    for _ in range(2):
        db = SQLiteStore(path)
        assert db.db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert [
            r[0] for r in db.db.execute("SELECT version FROM schema_migrations ORDER BY version")
        ] == [1, 2]
        db.close()
    app = create_app(load_settings({"PAYPROOF_ENV": "test", "PAYPROOF_DATA_DIR": str(tmp_path)}))
    assert app.test_client().get("/healthz").status_code == 200
    assert app.test_client().get("/readyz").status_code == 200


def test_case_correction_and_retry_keep_failed_history_and_reject_stale_posts(web):
    client = login(web)
    draft_id, _ = new_draft(web)
    assert post(client, f"/operator/baselines/{draft_id}", assertion()).status_code == 302
    baseline = vendor(web)
    response = post(
        client,
        "/operator/cases/new",
        {"vendor_id": str(baseline.vendor_id), "plain_text": "No payment destination supplied."},
    )
    case_id = UUID(response.location.rsplit("/", 1)[1])
    failed = current(web, case_id)
    assert failed.snapshot.evidence.extraction.failure_code
    assert step(web, case_id, "compare").status_code == 302
    assert current(web, case_id).snapshot.comparison.state == "UNCERTAIN"
    assert step(web, case_id, "verify", verify_data()).status_code == 409
    from payproof.fixtures import load_corpus

    text = next(
        r for r in load_corpus().requests if r.fixture_id == "demo-account-change"
    ).source.text
    old_revision = str(current(web, case_id).revision_id)
    replacement = {"revision_id": old_revision, "email": text}
    path = f"/operator/cases/{case_id}/sources"
    assert client.get(path).status_code == 200
    assert post(client, path, replacement).status_code == 302
    assert post(client, path, replacement).status_code == 409
    assert current(web, case_id).snapshot.review is None
    assert current(web, case_id).snapshot.comparison is None
    assert step(web, case_id, "review", {"source_review": "yes"}).status_code == 302
    assert step(web, case_id, "compare").status_code == 302
    assert current(web, case_id).snapshot.comparison.state == "VERIFY"
    old_revision = str(current(web, case_id).revision_id)
    assert step(web, case_id, "extract").status_code == 302
    assert (
        post(
            client, f"/operator/cases/{case_id}/extract", {"revision_id": old_revision}
        ).status_code
        == 409
    )
    assert current(web, case_id).snapshot.comparison is None
    db = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    assert db.case_history(case_id)[0].snapshot.evidence.extraction.failure_code
    db.close()


def test_revision_race_and_tampered_state_are_rejected(web):
    client = login(web)
    draft_id, _ = new_draft(web)
    assert post(client, f"/operator/baselines/{draft_id}", assertion()).status_code == 302
    prior = vendor(web)
    url = f"/operator/baselines/new?vendor_id={prior.vendor_id}"
    first, _ = new_draft(web, {"account": NEW, "expected_revision_id": str(prior.revision_id)}, url)
    second, _ = new_draft(web, {"expected_revision_id": str(prior.revision_id)}, url)
    assert post(client, f"/operator/baselines/{first}", assertion()).status_code == 302
    assert post(client, f"/operator/baselines/{second}", assertion()).status_code == 409
    assert post(client, url, {"expected_revision_id": str(prior.revision_id)}).status_code == 409
    assert (
        post(
            client, f"/operator/baselines/{first}", assertion() | {"state": "VERIFIED"}
        ).status_code
        == 400
    )
    assert vendor(web).payment_identity.account_identifier == NEW


def test_concurrent_baseline_confirmation_records_one_assertion(web):
    from concurrent.futures import ThreadPoolExecutor

    from payproof.baselines import BaselineAssertion

    login(web)
    draft_id, _ = new_draft(web)
    action = BaselineAssertion(
        draft_id=draft_id,
        operator_id="same-human",
        source_reviewed=True,
        previously_trusted=True,
        contact_independently_established=True,
        contact_method="PHONE",
        contact_value="+1-202-555-0144",
    )

    def confirm(_):
        db = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
        try:
            return db.assert_baseline(action).revision_id
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        revisions = list(pool.map(confirm, range(2)))
    assert revisions[0] == revisions[1]
    db = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    assert db.db.execute("SELECT count(*) FROM baseline_assertions").fetchone()[0] == 1
    assert db.db.execute("SELECT count(*) FROM vendor_revisions").fetchone()[0] == 1
    db.close()
