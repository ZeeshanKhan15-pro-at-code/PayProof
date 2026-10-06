"""Gated HTTP workflow integration; no real model or contact is used."""

import io
import re
import secrets
from uuid import UUID, uuid4

import pytest

from payproof.config import ConfigurationError, load_settings
from payproof.fixtures import load_corpus
from payproof.schemas import TrustedVendorRecord
from payproof.storage import SQLiteStore
from payproof.web import create_app


@pytest.fixture
def web(tmp_path):
    token = secrets.token_urlsafe(36)
    settings = load_settings(
        {
            "PAYPROOF_ENV": "test",
            "PAYPROOF_DATA_DIR": str(tmp_path),
            "PAYPROOF_SECRET_KEY": secrets.token_urlsafe(48),
            "PAYPROOF_OPERATOR_TOKEN": token,
            "PAYPROOF_EXTRACTION_MODE": "fixture",
        }
    )
    app = create_app(settings)
    return app, app.test_client(), settings, token


def csrf(client):
    with client.session_transaction() as session:
        return session["csrf"]


def login(web):
    _, client, _, token = web
    assert client.get("/operator/login").status_code == 200
    assert (
        client.post(
            "/operator/login",
            data={"csrf": csrf(client), "operator": "synthetic-human", "token": token},
        ).status_code
        == 302
    )
    return client


def post(client, path, data=None):
    return client.post(path, data={"csrf": csrf(client)} | (data or {}))


def demo_case(web, text=None, upload=False):
    client = login(web)
    assert post(client, "/operator/demo-vendor").status_code == 302
    fixture = next(r for r in load_corpus().requests if r.fixture_id == "demo-account-change")
    data = {"vendor_id": str(fixture.vendor_id)}
    if upload:
        data |= {
            "upload": (io.BytesIO((text or fixture.source.text).encode()), "invoice.txt"),
            "upload_kind": "EMAIL",
        }
    else:
        data["email"] = text or fixture.source.text
    response = post(client, "/operator/cases/new", data)
    assert response.status_code == 302, response.text
    case_id = UUID(response.location.rsplit("/", 1)[1])
    return client, case_id


def current(web, case_id):
    store = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    try:
        return store.get_case(case_id)
    finally:
        store.close()


def step(web, case_id, action, extra=None):
    return post(
        web[1],
        f"/operator/cases/{case_id}/{action}",
        {"revision_id": str(current(web, case_id).revision_id)} | (extra or {}),
    )


def verify_data():
    return {
        "action_id": str(uuid4()),
        "independently_checked": "yes",
        "what_was_checked": "EXACT_PAYMENT_DESTINATION_INSTRUCTIONS",
        "outcome": "CONFIRMED",
        "person": "Synthetic callback role",
        "notes": "Simulated independent check only.",
    }


def test_seeded_complete_workflow_preserves_distinct_states_and_history(web):
    client, case_id = demo_case(web)
    page = client.get(f"/operator/cases/{case_id}")
    assert page.status_code == 200
    assert "GB46TEST00000000003821" in page.text and "GB57TEST00000000009928" in page.text
    assert "Not acknowledged" in page.text and "No comparison state has been assigned" in page.text
    assert "Payment authorization: not provided" in page.text
    assert "source_review" in page.text and "independently_checked" not in page.text
    assert step(web, case_id, "review", {"source_review": "yes"}).status_code == 302
    assert current(web, case_id).snapshot.verification is None
    assert step(web, case_id, "compare").status_code == 302
    case = current(web, case_id)
    assert case.snapshot.comparison.state == "VERIFY"
    page = client.get(f"/operator/cases/{case_id}").text
    assert "Comparison state: VERIFY" in page and "Human attestation: NOT_VERIFIED" in page
    assert "DESTINATION_CHANGED" in page and "+1-202-555-0182" in page
    assert "synthetic-onboarding/demo-account-3821" in page
    assert "Characters" in page and "GB57TEST00000000009928" in page
    assert "checked" not in re.search(
        r'<input type="checkbox" name="independently_checked"[^>]*>', page
    ).group(0).replace("independently_checked", "")
    assert step(web, case_id, "verify", verify_data()).status_code == 302
    stored = current(web, case_id)
    assert stored.independent_verification_status == "VERIFIED"
    assert stored.snapshot.comparison.state == "VERIFY"
    page = client.get(f"/operator/cases/{case_id}").text
    assert "Human attestation: VERIFIED" in page and "Comparison state: VERIFY" in page
    assert "Case history" in page and "Version 4" in page and "CONFIRMED" in page
    store = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    assert len(store.case_history(case_id)) == 4
    assert (
        store.verification_events(case_id)[0].trusted_contact
        == stored.snapshot.baseline.callback_contact
    )
    store.close()
    # A new Flask process/session sees the same persisted case and attestation.
    restarted = create_app(web[2]).test_client()
    restarted.get("/operator/login")
    restarted.post(
        "/operator/login",
        data={"csrf": csrf(restarted), "operator": "another-human", "token": web[3]},
    )
    assert "Human attestation: VERIFIED" in restarted.get(f"/operator/cases/{case_id}").text


@pytest.mark.parametrize(
    "action, extra",
    [("review", {}), ("verify", verify_data()), ("compare", {"state": "UNCHANGED"})],
)
def test_actions_cannot_invent_review_verification_or_state(web, action, extra):
    _, case_id = demo_case(web)
    response = step(web, case_id, action, extra)
    assert response.status_code in (400, 409)
    assert current(web, case_id).snapshot.review is None
    assert current(web, case_id).snapshot.verification is None


def test_compare_without_review_is_uncertain_and_explained(web):
    client, case_id = demo_case(web)
    assert step(web, case_id, "compare").status_code == 302
    assert current(web, case_id).snapshot.comparison.state == "UNCERTAIN"
    page = client.get(f"/operator/cases/{case_id}").text
    assert "REVIEW_REQUIRED" in page and "have not received explicit human source review" in page
    assert "independently_checked" not in page
    assert step(web, case_id, "verify", verify_data()).status_code == 409


@pytest.mark.parametrize(
    "extra",
    [
        {"trusted_callback_value": "suspect@example.test"},
        {"state": "VERIFIED"},
        {"human_confirmed": "true"},
        {"operator_id": "AI"},
    ],
)
def test_forged_verification_fields_rejected(web, extra):
    _, case_id = demo_case(web)
    step(web, case_id, "review", {"source_review": "yes"})
    step(web, case_id, "compare")
    assert step(web, case_id, "verify", verify_data() | extra).status_code == 400
    assert current(web, case_id).snapshot.verification is None


@pytest.mark.parametrize("outcome", ["NOT_CONFIRMED", "INCONCLUSIVE"])
def test_negative_attempts_are_visible_without_verification(web, outcome):
    client, case_id = demo_case(web)
    step(web, case_id, "review", {"source_review": "yes"})
    step(web, case_id, "compare")
    assert (
        step(web, case_id, "verify", verify_data() | {"outcome": outcome, "person": ""}).status_code
        == 302
    )
    page = client.get(f"/operator/cases/{case_id}").text
    assert outcome in page and "Human attestation: NOT_VERIFIED" in page


def test_stale_revision_and_trusted_update_block_confirmation(web):
    client, case_id = demo_case(web)
    stale = current(web, case_id).revision_id
    step(web, case_id, "review", {"source_review": "yes"})
    step(web, case_id, "compare")
    assert (
        post(
            client, f"/operator/cases/{case_id}/verify", verify_data() | {"revision_id": str(stale)}
        ).status_code
        == 409
    )
    case = current(web, case_id)
    store = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    vendor = store.get_vendor(case.selected_vendor_id)
    updated = TrustedVendorRecord.model_validate(vendor.model_dump() | {"revision_id": uuid4()})
    store.put_vendor(updated, operator_id="trusted-human", expected_revision_id=vendor.revision_id)
    store.close()
    assert step(web, case_id, "verify", verify_data()).status_code == 409
    assert "STALE:" in client.get(f"/operator/cases/{case_id}").text
    assert step(web, case_id, "refresh").status_code == 302
    assert current(web, case_id).snapshot.review is None


def test_upload_text_and_failed_extraction_are_retained(web):
    client, case_id = demo_case(
        web, text="No usable destination. <script>alert(1)</script>", upload=True
    )
    page = client.get(f"/operator/cases/{case_id}")
    assert "&lt;script&gt;" in page.text and "<script>" not in page.text
    assert "NOT_CONFIGURED" in page.text
    assert step(web, case_id, "review", {"source_review": "yes"}).status_code == 400
    assert step(web, case_id, "compare").status_code == 302
    assert current(web, case_id).snapshot.comparison.state == "UNCERTAIN"
    assert step(web, case_id, "verify", verify_data()).status_code == 409


def test_login_csrf_origin_logout_and_private_rendering(web):
    _, client, settings, token = web
    assert client.get("/operator").status_code == 302
    assert client.post("/operator/demo-vendor").status_code == 401
    client.get("/operator/login")
    assert (
        client.post("/operator/login", data={"operator": "test", "token": token}).status_code == 403
    )
    assert (
        client.post(
            "/operator/login", data={"csrf": csrf(client), "operator": "test", "token": "wrong"}
        ).status_code
        == 401
    )
    login(web)
    assert client.post("/operator/demo-vendor").status_code == 403
    assert (
        client.post(
            "/operator/demo-vendor",
            data={"csrf": csrf(client)},
            headers={"Origin": "https://unrelated.example"},
        ).status_code
        == 403
    )
    page = client.get("/operator")
    assert page.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
    assert token not in page.text and settings.secret_key.get_secret_value() not in page.text
    assert post(client, "/operator/logout").status_code == 302
    assert client.get("/operator").status_code == 302
    assert client.post("/operator/demo-vendor").status_code == 401


@pytest.mark.parametrize("payload", ["x" * 100_001, "x" * 20_001])
def test_large_input_rejected_without_truncation_or_case(web, payload):
    client = login(web)
    post(client, "/operator/demo-vendor")
    vendor = next(
        v
        for v in load_corpus().vendors
        if v.canonical_vendor_name == "Synthetic PayProof Demo Supplies"
    )
    response = post(
        client, "/operator/cases/new", {"vendor_id": str(vendor.vendor_id), "email": payload}
    )
    assert response.status_code in (400, 413)
    store = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    assert store.list_cases() == ()
    store.close()


def test_gate_requires_both_secrets_and_is_disabled_by_default(tmp_path):
    app = create_app(load_settings({"PAYPROOF_DATA_DIR": str(tmp_path)}))
    assert app.test_client().get("/operator").status_code == 503
    assert not (tmp_path / "payproof.sqlite3").exists()
    with pytest.raises(ConfigurationError):
        load_settings({"PAYPROOF_OPERATOR_TOKEN": secrets.token_urlsafe(36)})


def test_create_trusted_vendor_requires_explicit_prior_trust(web):
    client = login(web)
    data = {
        "name": "Synthetic supplied vendor",
        "account": "GB46TEST00000000003821",
        "contact_method": "PHONE",
        "contact": "+1-202-555-0101",
        "source_reference": "synthetic-prior-onboarding",
        "description": "Synthetic prior contact and instructions",
        "verified_at": "2026-10-01T08:00:00Z",
    }
    assert post(client, "/operator/vendors/new", data).status_code == 400
    assert (
        post(client, "/operator/vendors/new", data | {"trusted_before_request": "yes"}).status_code
        == 302
    )
    store = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    assert store.list_vendors()[0].callback_contact.value == data["contact"]
    store.close()


@pytest.mark.parametrize(
    "fixture_id, expected",
    [
        ("unchanged", "UNCHANGED"),
        ("missing-destination", "UNCERTAIN"),
        ("unsupported-country", "UNCERTAIN"),
    ],
)
def test_fixture_states_use_backend_and_explain_uncertainty(web, fixture_id, expected):
    client = login(web)
    corpus = load_corpus()
    fixture = next(r for r in corpus.requests if r.fixture_id == fixture_id)
    vendor = next(v for v in corpus.vendors if v.vendor_id == fixture.vendor_id)
    store = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    store.put_vendor(vendor, operator_id="synthetic-seeder")
    store.close()
    name = {
        "EMAIL": "email",
        "INVOICE": "invoice",
        "PLAIN_TEXT": "plain_text",
        "VENDOR_NOTICE": "vendor_notice",
    }[fixture.source.kind]
    response = post(
        client,
        "/operator/cases/new",
        {"vendor_id": str(vendor.vendor_id), name: fixture.source.text},
    )
    assert response.status_code == 302
    case_id = UUID(response.location.rsplit("/", 1)[1])
    assert step(web, case_id, "review", {"source_review": "yes"}).status_code == 302
    assert step(web, case_id, "compare").status_code == 302
    case = current(web, case_id)
    assert case.snapshot.comparison.state == expected
    page = client.get(f"/operator/cases/{case_id}").text
    assert f"Comparison state: {expected}" in page
    for reason in case.snapshot.comparison.reason_codes:
        assert reason in page
    if expected == "UNCERTAIN":
        assert "independently_checked" not in page
        assert step(web, case_id, "verify", verify_data()).status_code == 409


@pytest.mark.parametrize("variant", ["missing", "competing", "timeout", "fabricated", "malformed"])
def test_mocked_live_extraction_failures_remain_unresolved(web, monkeypatch, variant):
    import json

    from test_extraction import wire_payload

    from payproof.openai_extraction import (
        OpenAIExtractionProvider,
        ProviderCompletion,
        ProviderFailure,
    )

    configured = web[2].model_dump() | {
        "extraction_mode": "live",
        "secret_key": web[2].secret_key,
        "operator_token": web[2].operator_token,
        "provider_api_key": __import__("pydantic").SecretStr(secrets.token_urlsafe(36)),
        "provider_model": "synthetic-mock-model",
    }
    settings = type(web[2]).model_validate(configured)
    app = create_app(settings)
    live_web = (app, app.test_client(), settings, web[3])

    def complete(self, sources):
        if variant == "timeout":
            raise ProviderFailure("TIMEOUT")
        values = (
            {}
            if variant == "missing"
            else {"account_identifier": [(0, "GB46TEST00000000003821", "GB46TEST00000000003821")]}
        )
        wire = wire_payload(sources, values)
        if variant == "fabricated":
            wire["account_identifier"]["candidates"][0]["exact_excerpt"] = "Fabricated destination"
        text = "{malformed" if variant == "malformed" else json.dumps(wire)
        return ProviderCompletion(text=text, model="synthetic-mock-model", raw_response=b"{}")

    monkeypatch.setattr(OpenAIExtractionProvider, "complete", complete)
    client, case_id = demo_case(
        live_web, text="Previous IBAN GB46TEST00000000003821. Current IBAN GB57TEST00000000009928."
    )
    case = current(live_web, case_id)
    if case.snapshot.evidence.extraction.failure_code is None:
        assert step(live_web, case_id, "review", {"source_review": "yes"}).status_code == 302
    else:
        assert step(live_web, case_id, "review", {"source_review": "yes"}).status_code == 400
    assert step(live_web, case_id, "compare").status_code == 302
    assert current(live_web, case_id).snapshot.comparison.state == "UNCERTAIN"
    assert step(live_web, case_id, "verify", verify_data()).status_code == 409
    assert "UNCERTAIN" in client.get(f"/operator/cases/{case_id}").text


def test_browser_entry_and_unknown_upload_are_safe(web):
    client = login(web)
    assert client.get("/", headers={"Accept": "text/html"}).location == "/operator"
    post(client, "/operator/demo-vendor")
    fixture = next(r for r in load_corpus().requests if r.fixture_id == "demo-account-change")
    response = post(
        client,
        "/operator/cases/new",
        {
            "vendor_id": str(fixture.vendor_id),
            "upload": (io.BytesIO(b"not PDF text"), "invoice.pdf"),
        },
    )
    assert response.status_code == 400


def test_non_ascii_auth_inputs_and_missing_independent_ack_fail_safely(web):
    _, client, _, _ = web
    client.get("/operator/login")
    assert (
        client.post(
            "/operator/login", data={"csrf": "é" * 40, "operator": "test", "token": "é" * 40}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/operator/login", data={"csrf": csrf(client), "operator": "test", "token": "é" * 40}
        ).status_code
        == 401
    )
    _, case_id = demo_case(web)
    step(web, case_id, "review", {"source_review": "yes"})
    step(web, case_id, "compare")
    data = verify_data()
    del data["independently_checked"]
    assert step(web, case_id, "verify", data).status_code == 400
    assert current(web, case_id).snapshot.verification is None


def test_operator_credentials_cannot_be_reflected_or_stored_as_source(web):
    client = login(web)
    post(client, "/operator/demo-vendor")
    fixture = next(r for r in load_corpus().requests if r.fixture_id == "demo-account-change")
    response = post(
        client, "/operator/cases/new", {"vendor_id": str(fixture.vendor_id), "email": web[3]}
    )
    assert response.status_code == 400 and web[3] not in response.text
    store = SQLiteStore(web[2].data_dir / "payproof.sqlite3")
    assert store.list_cases() == ()
    store.close()


def test_login_burst_limit_and_production_cookies(web):
    _, client, settings, token = web
    client.get("/operator/login")
    for _ in range(5):
        assert (
            client.post(
                "/operator/login", data={"csrf": csrf(client), "operator": "test", "token": "wrong"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/operator/login", data={"csrf": csrf(client), "operator": "test", "token": token}
        ).status_code
        == 429
    )
    production = type(settings).model_validate(
        settings.model_dump()
        | {
            "environment": "production",
            "secret_key": settings.secret_key,
            "operator_token": settings.operator_token,
        }
    )
    response = create_app(production).test_client().get("/operator/login")
    cookie = response.headers["Set-Cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie


def test_seeded_browser_prefill_and_form_line_endings(web):
    client = login(web)
    post(client, "/operator/demo-vendor")
    page = client.get("/operator/cases/new?demo=1").text
    assert '<textarea name="email" maxlength="20000">From:' in page
    fixture = next(r for r in load_corpus().requests if r.fixture_id == "demo-account-change")
    response = post(
        client,
        "/operator/cases/new",
        {"vendor_id": str(fixture.vendor_id), "email": fixture.source.text.replace("\n", "\r\n")},
    )
    assert response.status_code == 302
    case_id = UUID(response.location.rsplit("/", 1)[1])
    case = current(web, case_id)
    assert case.snapshot.sources[0].text == fixture.source.text
    assert case.snapshot.evidence.extraction.method == "FIXTURE"
    step(web, case_id, "review", {"source_review": "yes"})
    step(web, case_id, "compare")
    assert current(web, case_id).snapshot.comparison.state == "VERIFY"
