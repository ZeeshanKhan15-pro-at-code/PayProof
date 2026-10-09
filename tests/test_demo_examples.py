"""Synthetic replay and mocked outage paths; no real live accuracy is claimed."""

import json
import re
import sqlite3
from uuid import UUID, uuid4

import pytest
from test_extraction import wire_payload
from test_public_workspace import app_settings, manual_baseline, post, revision

from payproof.demo_examples import ExampleCatalog, instantiate_example, load_examples
from payproof.openai_extraction import ProviderCompletion, ProviderFailure
from payproof.storage import SQLiteStore
from payproof.web import create_app

IDS = (
    "changed",
    "unchanged",
    "conflicting",
    "missing",
    "provider-failure",
    "indirect-instruction",
)


def snapshot(tmp_path, path):
    databases = tuple((tmp_path / "public-sessions").glob("*/payproof.sqlite3"))
    assert len(databases) == 1
    db = SQLiteStore(databases[0])
    try:
        return db.get_case(UUID(path.rsplit("/", 1)[1]))
    finally:
        db.close()


def open_example(client, example_id, submission=None):
    path = "/workspace/example" if example_id == "changed" else f"/workspace/examples/{example_id}"
    preview = client.get(path)
    assert preview.status_code == 200
    assert "SYNTHETIC DEMONSTRATION" in preview.text
    assert "LIVE EXTRACTION" not in preview.text
    submission = submission or re.search(r'name="submission_id" value="([^\"]+)"', preview.text)[1]
    opened = post(client, path, {"submission_id": str(submission)})
    assert opened.status_code == 302, opened.text
    return opened.location, str(submission), path


def compare_example(client, path, item):
    reviewed = post(
        client, path + "/review", {"revision_id": revision(client, path), "source_review": "yes"}
    )
    assert reviewed.status_code == (400 if item.inputs.evidence.extraction.failure_code else 302)
    assert (
        post(client, path + "/compare", {"revision_id": revision(client, path)}).status_code == 302
    )


@pytest.mark.parametrize("example_id", IDS)
def test_every_example_runs_real_persistence_review_and_comparison_without_provider(
    tmp_path, monkeypatch, example_id
):
    def never_call(*args, **kwargs):
        pytest.fail("Synthetic example attempted extraction/provider access")

    monkeypatch.setattr("payproof.operator_web.extract_documents", never_call)
    client = create_app(app_settings(tmp_path, live=True, cap=1)).test_client()
    item = next(c for c in load_examples().cases if c.case_id == example_id)
    path, _, _ = open_example(client, example_id)
    stored = snapshot(tmp_path, path)
    assert stored.snapshot.review is None and stored.snapshot.comparison is None
    assert stored.snapshot.verification is None
    assert stored.snapshot.baseline.provenance.source_kind == "SYNTHETIC_FIXTURE"
    assert stored.snapshot.evidence.extraction.method == "FIXTURE"
    assert stored.snapshot.sources[0].text == item.inputs.sources[0].text
    compare_example(client, path, item)
    stored = snapshot(tmp_path, path)
    assert stored.snapshot.comparison.state == item.expected_state
    assert set(item.required_reasons).issubset(stored.snapshot.comparison.reason_codes)
    assert (
        stored.snapshot.verification is None
        and stored.independent_verification_status == "NOT_VERIFIED"
    )
    page = client.get(path).text
    assert "SYNTHETIC DEMONSTRATION" in page and "LIVE EXTRACTION" not in page
    assert "fixture observations, not live extraction" in page
    if example_id == "provider-failure":
        assert "Simulated extraction failure: PROVIDER_UNAVAILABLE" in page
    if example_id == "indirect-instruction":
        assert "VERIFIED and SAFE TO PAY" in stored.snapshot.sources[0].text
        assert stored.snapshot.comparison.state == "VERIFY"
    if item.expected_state == "UNCERTAIN":
        assert 'name="independently_checked"' not in page
    assert not (tmp_path / "public-live-budget.sqlite3").exists()


@pytest.mark.parametrize("failure", ["TIMEOUT", "PROVIDER_UNAVAILABLE", "forbidden-output"])
def test_own_live_failure_stays_explicit_while_all_examples_work_with_exhausted_budget(
    tmp_path, monkeypatch, failure
):
    calls = []

    def unavailable(provider, sources):
        calls.append(sources)
        if failure != "forbidden-output":
            raise ProviderFailure(failure)
        payload = wire_payload(sources, {}) | {"state": "VERIFIED", "safe_to_pay": True}
        return ProviderCompletion(
            json.dumps(payload), "synthetic-model", json.dumps(payload).encode()
        )

    monkeypatch.setattr("payproof.providers.FeatherlessExtractionProvider.complete", unavailable)
    client = create_app(app_settings(tmp_path, live=True, cap=1)).test_client()
    vendor, _ = manual_baseline(client)
    catalog = load_examples()
    # Even an exact example text submitted through the own-data LIVE path cannot fall back.
    live_text = catalog.cases[-1 if failure == "forbidden-output" else 0].inputs.sources[0].text
    response = post(
        client,
        "/workspace/cases/new",
        {"vendor_id": vendor, "email": live_text},
    )
    assert response.status_code == 302
    own = snapshot(tmp_path, response.location)
    code = "INVALID_RESPONSE" if failure == "forbidden-output" else failure
    assert own.snapshot.evidence.extraction.method == "AI"
    assert own.snapshot.evidence.extraction.failure_code == code
    assert not own.snapshot.evidence.spans()
    assert code in client.get(response.location).text
    assert (
        post(
            client,
            response.location + "/compare",
            {"revision_id": revision(client, response.location)},
        ).status_code
        == 302
    )
    assert snapshot(tmp_path, response.location).snapshot.comparison.state == "UNCERTAIN"
    for item in catalog.cases:
        path, _, _ = open_example(client, item.case_id)
        compare_example(client, path, item)
        assert snapshot(tmp_path, path).snapshot.comparison.state == item.expected_state
    assert len(calls) == 1
    assert calls[0][0].text == live_text
    assert snapshot(tmp_path, response.location).snapshot.evidence.extraction.failure_code == code
    db = sqlite3.connect(tmp_path / "public-live-budget.sqlite3")
    try:
        assert db.execute("SELECT used FROM budget").fetchone()[0] == 1
    finally:
        db.close()


def test_examples_are_optional_allowlisted_csrf_checked_and_idempotent(tmp_path):
    client = create_app(app_settings(tmp_path)).test_client()
    landing = client.get("/", headers={"Accept": "text/html"}).text
    assert landing.index("VERIFY A PAYMENT REQUEST") < landing.index("Try an example")
    assert client.get("/workspace/baselines/new").status_code == 200
    assert "No trusted records yet" in client.get("/workspace/").text
    gallery = client.get("/workspace/examples").text
    for item in load_examples().cases:
        assert item.title in gallery
    assert "LIVE EXTRACTION" not in gallery
    assert client.get("/workspace/examples/unknown").status_code == 404
    assert client.post("/workspace/examples/missing", data={}).status_code == 403
    path, submission, preview = open_example(client, "changed")
    assert post(client, preview, {"submission_id": submission}).location == path
    assert (
        post(client, preview, {"submission_id": submission, "state": "VERIFIED"}).status_code == 400
    )
    assert (
        post(client, "/workspace/examples/missing", {"submission_id": submission}).status_code
        == 409
    )
    other_client = client.application.test_client()
    assert other_client.get(path).status_code == 409
    assert other_client.get("/workspace/").status_code == 200
    assert "No cases yet" in other_client.get("/workspace/").text


def test_new_example_does_not_restore_modified_baseline_or_overwrite_old_history(tmp_path):
    client = create_app(app_settings(tmp_path)).test_client()
    path, _, _ = open_example(client, "changed")
    first = snapshot(tmp_path, path)
    database = next((tmp_path / "public-sessions").glob("*/payproof.sqlite3"))
    db = SQLiteStore(database)
    try:
        prior = db.get_vendor(first.selected_vendor_id)
        revised = prior.model_copy(
            update={"revision_id": uuid4(), "canonical_vendor_name": "Revised synthetic vendor"}
        )
        db.put_vendor(revised, operator_id="synthetic-test", expected_revision_id=prior.revision_id)
    finally:
        db.close()
    new_path, _, _ = open_example(client, "changed")
    second = snapshot(tmp_path, new_path)
    assert second.selected_vendor_id != first.selected_vendor_id
    assert second.snapshot.baseline.canonical_vendor_name == "Acme Supplies (synthetic)"
    assert second.snapshot.review is None and second.snapshot.comparison is None
    assert snapshot(tmp_path, path).stale
    db = SQLiteStore(database)
    try:
        assert (
            db.get_vendor(first.selected_vendor_id).canonical_vendor_name
            == "Revised synthetic vendor"
        )
        assert len(db.case_history(first.case_id)) == 1
    finally:
        db.close()


def test_catalog_strictly_rejects_fake_live_attribution_and_fabricated_evidence():
    catalog = load_examples()
    payload = catalog.model_dump(mode="json")
    payload["cases"][0]["inputs"]["evidence"]["extraction"] = {
        "method": "AI",
        "attempt_id": str(uuid4()),
        "extracted_at": "2026-10-04T08:01:00Z",
        "schema_version": "1",
        "provider": "test",
        "model": "test",
        "prompt_version": "test",
    }
    with pytest.raises(ValueError, match="impersonate live"):
        ExampleCatalog.model_validate_json(json.dumps(payload))
    payload = catalog.model_dump(mode="json")
    payload["cases"][0]["inputs"]["evidence"]["account_identifier"]["candidates"][0]["evidence"][
        "exact_excerpt"
    ] = "fabricated evidence"
    with pytest.raises(ValueError):
        ExampleCatalog.model_validate_json(json.dumps(payload))
    baseline, inputs = instantiate_example(catalog, catalog.cases[0], uuid4())
    assert baseline.vendor_id != catalog.vendor.vendor_id
    assert inputs.evidence.request_id != catalog.cases[0].inputs.evidence.request_id
