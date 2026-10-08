"""No-login mounted Flask/SQLite tests. Live responses are mocked, never live accuracy."""

import json
import re
import secrets
from uuid import uuid4

from test_extraction import wire_payload

from payproof.config import load_settings
from payproof.demo_proof import load_demo
from payproof.openai_extraction import ProviderCompletion, ProviderFailure
from payproof.storage import SQLiteStore
from payproof.web import create_app

OLD = "GB46TEST00000000003821"
NEW = "GB57TEST00000000009928"


def app_settings(tmp_path, live=False, cap=20):
    return load_settings(
        {
            "PAYPROOF_ENV": "test",
            "PAYPROOF_DATA_DIR": str(tmp_path),
            "PAYPROOF_SECRET_KEY": secrets.token_urlsafe(48),
            "PAYPROOF_OPERATOR_TOKEN": secrets.token_urlsafe(48),
            "PAYPROOF_EXTRACTION_MODE": "live" if live else "fixture",
            "PAYPROOF_PROVIDER": "featherless",
            "PAYPROOF_PROVIDER_MODEL": "synthetic-model",
            "PAYPROOF_PROVIDER_API_KEY": secrets.token_urlsafe(40),
            "PAYPROOF_PUBLIC_LIVE_ENABLED": "true" if live else "false",
            "PAYPROOF_PUBLIC_LIVE_MAX_CALLS": str(cap),
        }
    )


def csrf(client):
    page = client.get("/workspace/")
    assert page.status_code == 200, page.text
    return re.search(r'name="csrf" value="([^"]+)"', page.text)[1]


def post(client, path, data=None):
    return client.post(path, data={"csrf": csrf(client)} | (data or {}))


def manual_baseline(client):
    response = post(
        client,
        "/workspace/baselines/new",
        {
            "name": "Own test vendor",
            "account": OLD,
            "verified_at": "2026-10-01T08:00:00Z",
            "source_reference": "previous test record",
            "description": "Independently known test destination",
        },
    )
    assert response.status_code == 302, response.text
    draft_path = response.location
    page = client.get(draft_path)
    assert "no trust conferred" in page.text
    assert (
        post(
            client,
            draft_path,
            {
                "source_reviewed": "yes",
                "previously_trusted": "yes",
                "contact_independently_established": "yes",
                "contact_method": "PHONE",
                "contact": "+1-202-555-0144",
            },
        ).status_code
        == 302
    )
    page = client.get("/workspace/cases/new").text
    vendor = re.search(r'<option value="([a-f0-9-]{36})"', page)[1]
    return vendor, draft_path


def mock_provider(monkeypatch, failure=False):
    calls = []

    def complete(provider, sources):
        calls.append(sources)
        if failure:
            raise ProviderFailure("TIMEOUT")
        account = NEW if NEW in sources[0].text else OLD
        payload = wire_payload(
            sources,
            {
                "account_identifier": [(0, account, account)],
                "destination_scheme": [(0, "IBAN", "IBAN")],
            },
        )
        raw = json.dumps(payload).encode()
        return ProviderCompletion(raw.decode(), "synthetic-model", raw)

    monkeypatch.setattr("payproof.providers.FeatherlessExtractionProvider.complete", complete)
    return calls


def revision(client, path):
    return re.search(r'name="revision_id" value="([a-f0-9-]{36})"', client.get(path).text)[1]


def test_landing_no_login_primary_own_data_and_private_isolation(tmp_path):
    settings = app_settings(tmp_path)
    private = SQLiteStore(tmp_path / "payproof.sqlite3")
    record = load_demo().vendor
    private.put_vendor(record, operator_id="private-test-operator")
    private.create_case(
        load_demo().cases[0].inputs, record.vendor_id, operator_id="private-test-operator"
    )
    private.close()
    app = create_app(settings)
    a, b = app.test_client(), app.test_client()
    landing = a.get("/", headers={"Accept": "text/html"})
    assert landing.status_code == 200
    assert landing.text.index("VERIFY A PAYMENT REQUEST") < landing.text.index("See an example")
    assert "PDF, MSG and OCR are not parsed" in landing.text
    assert a.get("/workspace/login").status_code == 404
    home = a.get("/workspace/")
    assert home.status_code == 200 and "Acme" not in home.text
    vendor_id, draft = manual_baseline(a)
    assert b.get(draft).status_code == 409
    assert (
        post(
            b, "/workspace/cases/new", {"vendor_id": vendor_id, "plain_text": "No destination"}
        ).status_code
        == 409
    )
    private_id = load_demo().cases[0].inputs.evidence.request_id
    assert a.get(f"/workspace/cases/{private_id}").status_code == 409
    assert a.get(f"/operator/cases/{private_id}").status_code == 302
    assert a.get("/workspace/").headers["Cache-Control"] == "no-store"
    assert "HttpOnly" in home.headers.get("Set-Cookie", "")
    assert len(list((tmp_path / "public-sessions").glob("*/payproof.sqlite3"))) == 2


def test_own_data_live_contract_review_compare_human_receipt_and_isolation(tmp_path, monkeypatch):
    calls = mock_provider(monkeypatch)
    app = create_app(app_settings(tmp_path, live=True))
    a, b = app.test_client(), app.test_client()
    vendor, _ = manual_baseline(a)
    data = {"vendor_id": vendor, "invoice": f"Pay to IBAN {NEW}.", "submission_id": str(uuid4())}
    response = post(a, "/workspace/cases/new", data)
    assert response.status_code == 302, response.text
    path = response.location
    assert "LIVE EXTRACTION" in a.get(path).text and "Not acknowledged" in a.get(path).text
    assert post(a, "/workspace/cases/new", data).location == path
    assert len(calls) == 1
    assert b.get(path).status_code == 409
    assert (
        post(
            a, path + "/review", {"revision_id": revision(a, path), "source_review": "yes"}
        ).status_code
        == 302
    )
    assert post(a, path + "/compare", {"revision_id": revision(a, path)}).status_code == 302
    assert "Comparison state: VERIFY" in a.get(path).text
    assert "+1-202-555-0144" in a.get(path).text
    assert (
        post(
            a,
            path + "/verify",
            {
                "revision_id": revision(a, path),
                "action_id": str(uuid4()),
                "independently_checked": "yes",
                "what_was_checked": "EXACT_PAYMENT_DESTINATION_INSTRUCTIONS",
                "outcome": "CONFIRMED",
                "person": "Synthetic independent human",
                "notes": "<script>synthetic_note()</script>",
            },
        ).status_code
        == 302
    )
    page = a.get(path).text
    receipt_path = re.search(r'href="([^\"]+/receipts/[^\"]+)"', page)[1]
    receipt = a.get(receipt_path)
    assert receipt.status_code == 200 and receipt.json["current"]
    assert receipt.json["payment_authorization"] == "NOT_PROVIDED"
    html = a.get(receipt_path, headers={"Accept": "text/html"})
    assert "Independent human attestation receipt" in html.text
    assert "<script>synthetic_note()" not in html.text
    assert "&lt;script&gt;synthetic_note()" in html.text
    assert b.get(receipt_path).status_code == 409
    assert a.get("/workspace/").status_code == 200


def test_public_live_disabled_does_not_call_provider_and_example_is_secondary(
    tmp_path, monkeypatch
):
    calls = mock_provider(monkeypatch)
    app = create_app(app_settings(tmp_path))
    client = app.test_client()
    vendor, _ = manual_baseline(client)
    response = post(
        client, "/workspace/cases/new", {"vendor_id": vendor, "invoice": f"Pay to IBAN {NEW}."}
    )
    assert response.status_code == 302
    assert "NOT_CONFIGURED" in client.get(response.location).text
    assert calls == []
    preview = client.get("/workspace/example")
    assert "DEMO EXAMPLE" in preview.text
    sample = post(client, "/workspace/example")
    assert sample.status_code == 302
    assert "fixture observations, not live extraction" in client.get(sample.location).text
    assert "Acme" in client.get("/workspace/").text
    assert calls == []


def test_durable_global_budget_and_provider_errors_fail_closed(tmp_path, monkeypatch):
    calls = mock_provider(monkeypatch, failure=True)
    settings = app_settings(tmp_path, live=True, cap=1)
    app = create_app(settings)
    client = app.test_client()
    vendor, _ = manual_baseline(client)
    response = post(
        client, "/workspace/cases/new", {"vendor_id": vendor, "invoice": f"Pay to IBAN {NEW}."}
    )
    assert "TIMEOUT" in client.get(response.location).text
    assert (
        post(
            client,
            response.location + "/review",
            {"revision_id": revision(client, response.location), "source_review": "yes"},
        ).status_code
        == 400
    )
    denied = post(
        client,
        "/workspace/cases/new",
        {"vendor_id": vendor, "invoice": f"Pay to IBAN {NEW}.", "submission_id": str(uuid4())},
    )
    assert denied.status_code == 429 and "allowance is exhausted" in denied.text
    assert len(calls) == 1
    restarted = create_app(settings).test_client()
    new_vendor, _ = manual_baseline(restarted)
    assert (
        post(
            restarted,
            "/workspace/cases/new",
            {"vendor_id": new_vendor, "invoice": f"Pay to IBAN {NEW}."},
        ).status_code
        == 429
    )
    assert len(calls) == 1


def test_public_csrf_and_expired_session_cannot_access_old_cases(tmp_path):
    app = create_app(app_settings(tmp_path))
    client = app.test_client()
    assert client.post("/workspace/baselines/new", data={}).status_code == 403
    vendor, draft = manual_baseline(client)
    assert client.post(draft, data={"csrf": "tampered"}).status_code == 403
    assert post(client, "/workspace/logout").status_code == 302
    assert client.get(draft).status_code == 409
    assert vendor not in client.get("/workspace/").text


def test_public_upload_errors_are_actionable_and_do_not_store_cases(tmp_path):
    import io

    client = create_app(app_settings(tmp_path)).test_client()
    vendor, _ = manual_baseline(client)
    unsupported = post(
        client,
        "/workspace/cases/new",
        {"vendor_id": vendor, "upload": (io.BytesIO(b"test"), "invoice.pdf")},
    )
    assert unsupported.status_code == 400 and "PDF, MSG" in unsupported.text
    invalid = post(
        client,
        "/workspace/cases/new",
        {"vendor_id": vendor, "upload": (io.BytesIO(b"\xff\xfe"), "invoice.txt")},
    )
    assert invalid.status_code == 400 and "not valid UTF8" in invalid.text
    empty = post(client, "/workspace/cases/new", {"vendor_id": vendor})
    assert empty.status_code == 400 and "Paste the current request" in empty.text
