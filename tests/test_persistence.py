"""Durability and explicit-human-action regression tests (synthetic only)."""

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from payproof.schemas import CaseContract, TrustedVendorRecord
from payproof.storage import SQLiteStore, WorkflowError
from payproof.workflow_contracts import CaseInputs, IndependentCheckAction
from tests.examples import valid_case


def inputs(state: str = "VERIFY") -> tuple[TrustedVendorRecord, CaseInputs]:
    case = CaseContract.model_validate_json(json.dumps(valid_case(state=state)))
    assert case.baseline
    return case.baseline, CaseInputs(sources=case.sources, evidence=case.evidence)


def action(outcome: str = "CONFIRMED") -> IndependentCheckAction:
    return IndependentCheckAction.model_validate(
        {
            "action_id": uuid4(),
            "operator_id": "synthetic-human",
            "independently_checked": True,
            "what_was_checked": "EXACT_PAYMENT_DESTINATION_INSTRUCTIONS",
            "outcome": outcome,
            "independently_reached_person": "Synthetic vendor role",
        }
    )


def ready(store: SQLiteStore):
    vendor, data = inputs()
    store.put_vendor(vendor, operator_id="operator")
    case = store.create_case(data, vendor.vendor_id, operator_id="operator")
    case = store.review(
        case.case_id,
        case.revision_id,
        operator_id="operator",
        destination_instructions_checked=True,
    )
    return store.compare(case.case_id, case.revision_id, operator_id="operator")


def test_restart_and_confirmation(tmp_path: Path):
    path = tmp_path / "cases.sqlite3"
    store = SQLiteStore(path)
    case = ready(store)
    command = action()
    event = store.record_independent_check(case.case_id, case.revision_id, command)
    assert event.trusted_contact == case.snapshot.baseline.callback_contact
    assert store.record_independent_check(case.case_id, case.revision_id, command) == event
    saved = store.get_case(case.case_id)
    assert saved.snapshot.comparison.state == "VERIFY"
    assert saved.independent_verification_status == "VERIFIED"
    assert store.get_case(case.case_id, case.revision_id).stale
    store.close()
    store = SQLiteStore(path)
    assert store.get_case(case.case_id) == saved
    assert store.verification_events(case.case_id) == (event,)
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == 1
    assert path.stat().st_mode & 0o777 == 0o600
    store.close()


@pytest.mark.parametrize("outcome", ["NOT_CONFIRMED", "INCONCLUSIVE"])
def test_negative_outcome_is_not_verified(tmp_path: Path, outcome: str):
    store = SQLiteStore(tmp_path / "db")
    case = ready(store)
    event = store.record_independent_check(case.case_id, case.revision_id, action(outcome))
    assert event.confirmation is None
    assert store.get_case(case.case_id).independent_verification_status == "NOT_VERIFIED"
    assert store.verification_events(case.case_id) == (event,)


def test_vendor_change_requires_refresh_review_comparison(tmp_path: Path):
    store = SQLiteStore(tmp_path / "db")
    case = ready(store)
    vendor = store.get_vendor(case.selected_vendor_id)
    updated = TrustedVendorRecord.model_validate(vendor.model_dump() | {"revision_id": uuid4()})
    store.put_vendor(updated, operator_id="operator", expected_revision_id=vendor.revision_id)
    assert store.get_case(case.case_id).stale
    with pytest.raises(WorkflowError, match="stale"):
        store.record_independent_check(case.case_id, case.revision_id, action())
    data = CaseInputs(sources=case.snapshot.sources, evidence=case.snapshot.evidence)
    case = store.replace_inputs(case.case_id, case.revision_id, data, operator_id="operator")
    assert case.snapshot.review is None and case.snapshot.comparison is None
    with pytest.raises(WorkflowError, match="reviewed"):
        store.record_independent_check(case.case_id, case.revision_id, action())
    case = store.review(
        case.case_id,
        case.revision_id,
        operator_id="operator",
        destination_instructions_checked=True,
    )
    case = store.compare(case.case_id, case.revision_id, operator_id="operator")
    store.record_independent_check(case.case_id, case.revision_id, action())


def test_concurrent_revision_and_retry_after_change(tmp_path: Path):
    path = tmp_path / "db"
    store = SQLiteStore(path)
    case = ready(store)
    second = SQLiteStore(path)
    command = action()
    store.record_independent_check(case.case_id, case.revision_id, command)
    with pytest.raises(WorkflowError, match="stale"):
        second.record_independent_check(case.case_id, case.revision_id, action())
    latest = store.get_case(case.case_id)
    store.replace_inputs(
        case.case_id,
        latest.revision_id,
        CaseInputs(sources=latest.snapshot.sources, evidence=latest.snapshot.evidence),
        operator_id="operator",
    )
    with pytest.raises(WorkflowError, match="stale"):
        store.record_independent_check(case.case_id, case.revision_id, command)


def test_failed_transaction_never_leaves_confirmation(tmp_path: Path):
    store = SQLiteStore(tmp_path / "db")
    case = ready(store)
    store.db.execute(
        "CREATE TRIGGER simulated_disk_failure BEFORE INSERT ON human_confirmations BEGIN SELECT RAISE(ABORT,'simulated failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.record_independent_check(case.case_id, case.revision_id, action())
    assert store.get_case(case.case_id) == case
    assert store.verification_events(case.case_id) == ()


@pytest.mark.parametrize("state", ["VERIFY", "UNCERTAIN"])
def test_no_review_or_uncertainty_cannot_confirm(tmp_path: Path, state: str):
    vendor, data = inputs(state)
    store = SQLiteStore(tmp_path / "db")
    store.put_vendor(vendor, operator_id="operator")
    case = store.create_case(data, vendor.vendor_id, operator_id="operator")
    case = store.compare(case.case_id, case.revision_id, operator_id="operator")
    with pytest.raises(WorkflowError):
        store.record_independent_check(case.case_id, case.revision_id, action())
    if state == "UNCERTAIN":
        case = store.review(
            case.case_id,
            case.revision_id,
            operator_id="operator",
            destination_instructions_checked=True,
        )
        case = store.compare(case.case_id, case.revision_id, operator_id="operator")
        with pytest.raises(WorkflowError):
            store.record_independent_check(case.case_id, case.revision_id, action())


@pytest.mark.parametrize(
    "extra",
    [
        {"trusted_callback_value": "suspect-contact"},
        {"confirmed_at": "2026-10-06T00:00:00Z"},
        {"state": "VERIFIED"},
        {"independently_checked": "true"},
    ],
)
def test_human_action_rejects_client_authority(extra: dict):
    with pytest.raises(ValidationError):
        IndependentCheckAction.model_validate(action().model_dump() | extra)


def test_import_cannot_supply_review_or_verification():
    with pytest.raises(ValidationError):
        CaseInputs.model_validate(valid_case(verified=True))


def test_immutable_sources_attempts_contacts_and_history(tmp_path: Path):
    store = SQLiteStore(tmp_path / "db")
    case = ready(store)
    data = CaseInputs(sources=case.snapshot.sources, evidence=case.snapshot.evidence)
    altered = data.model_dump()
    altered["sources"] = (data.sources[0].model_dump() | {"label": "Changed label"},)
    with pytest.raises(WorkflowError, match="immutable"):
        store.replace_inputs(
            case.case_id,
            case.revision_id,
            CaseInputs.model_validate(altered),
            operator_id="operator",
        )
    altered = data.model_dump()
    altered["evidence"]["extraction"]["warnings"] = ("Changed warning",)
    # Use an accepted metadata field rather than unsupported provider extras.
    altered["evidence"]["extraction"].pop("warnings", None)
    altered["evidence"]["extraction"]["model"] = "changed-model"
    with pytest.raises(WorkflowError, match="immutable"):
        store.replace_inputs(
            case.case_id,
            case.revision_id,
            CaseInputs.model_validate(altered),
            operator_id="operator",
        )
    vendor = store.get_vendor(case.selected_vendor_id)
    payload = vendor.model_dump()
    payload["revision_id"] = uuid4()
    payload["callback_contact"]["value"] = "+1-202-555-0199"
    with pytest.raises(WorkflowError, match="immutable"):
        store.put_vendor(
            TrustedVendorRecord.model_validate(payload),
            operator_id="operator",
            expected_revision_id=vendor.revision_id,
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store.db.execute("DELETE FROM case_revisions")
    assert store.get_case(case.case_id) == case


def test_unknown_migration_is_rejected(tmp_path: Path):
    path = tmp_path / "db"
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version=99")
    db.close()
    with pytest.raises(WorkflowError, match="version"):
        SQLiteStore(path)


def test_engine_revision_blocks_verification(tmp_path: Path, monkeypatch):
    store = SQLiteStore(tmp_path / "db")
    case = ready(store)
    monkeypatch.setattr("payproof.storage.engine_fingerprint", lambda: "new-engine-version")
    assert store.get_case(case.case_id).stale
    with pytest.raises(WorkflowError, match="stale"):
        store.record_independent_check(case.case_id, case.revision_id, action())


def test_repeated_confirmation_and_changed_idempotent_action_rejected(tmp_path: Path):
    store = SQLiteStore(tmp_path / "db")
    case = ready(store)
    command = action()
    store.record_independent_check(case.case_id, case.revision_id, command)
    latest = store.get_case(case.case_id)
    with pytest.raises(WorkflowError, match="confirmed"):
        store.record_independent_check(case.case_id, latest.revision_id, action())
    changed = IndependentCheckAction.model_validate(
        command.model_dump() | {"notes": "Different submission"}
    )
    with pytest.raises(WorkflowError, match="identifier"):
        store.record_independent_check(case.case_id, case.revision_id, changed)


def test_corrupted_snapshot_fails_closed(tmp_path: Path):
    store = SQLiteStore(tmp_path / "db")
    case = ready(store)
    store.db.execute("DROP TRIGGER immutable_cases_update")
    store.db.execute(
        "UPDATE case_revisions SET payload='{}' WHERE revision_id=?", (str(case.revision_id),)
    )
    with pytest.raises(WorkflowError, match="corrupt"):
        store.get_case(case.case_id)


def test_local_cli_requires_explicit_actions(tmp_path: Path, monkeypatch, capsys):
    from payproof.workflow_cli import main

    monkeypatch.setenv("PAYPROOF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PAYPROOF_EXTRACTION_MODE", "fixture")
    assert main(["init"]) == 0
    store = SQLiteStore(tmp_path / "payproof.sqlite3")
    case = ready(store)
    arguments = [
        "verify",
        "--case-id",
        str(case.case_id),
        "--revision-id",
        str(case.revision_id),
        "--operator",
        "synthetic-human",
    ]
    responses = iter(["Synthetic role", "CONFIRMED", "Synthetic demonstration", "cancel"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    assert main(arguments) == 1
    assert store.get_case(case.case_id).independent_verification_status == "NOT_VERIFIED"
    responses = iter(
        ["Synthetic role", "CONFIRMED", "Synthetic demonstration", "RECORD INDEPENDENT CHECK"]
    )
    assert main(arguments) == 0
    assert store.get_case(case.case_id).independent_verification_status == "VERIFIED"
    output = capsys.readouterr().out
    assert "+1-202-555-0100" in output
    assert "does not establish account ownership" in output
    assert main(["show", "--case-id", str(case.case_id)]) == 0
    assert store.get_case(case.case_id).snapshot.comparison.state == "VERIFY"


def test_competing_omitted_account_cannot_be_verified(tmp_path: Path):
    from hashlib import sha256

    from payproof.schemas import SourceDocument
    from tests.examples import GB_IBAN

    vendor, data = inputs()
    text = data.sources[0].text + "\nOld account: " + GB_IBAN
    source = SourceDocument.model_validate(
        data.sources[0].model_dump() | {"text": text, "sha256": sha256(text.encode()).hexdigest()}
    )
    store = SQLiteStore(tmp_path / "db")
    store.put_vendor(vendor, operator_id="operator")
    case = store.create_case(
        CaseInputs(sources=(source,), evidence=data.evidence),
        vendor.vendor_id,
        operator_id="operator",
    )
    case = store.review(
        case.case_id,
        case.revision_id,
        operator_id="operator",
        destination_instructions_checked=True,
    )
    case = store.compare(case.case_id, case.revision_id, operator_id="operator")
    assert case.snapshot.comparison.state == "UNCERTAIN"
    with pytest.raises(WorkflowError):
        store.record_independent_check(case.case_id, case.revision_id, action())


def test_corrected_observations_clear_confirmation_keep_history(tmp_path: Path):
    from hashlib import sha256

    store = SQLiteStore(tmp_path / "db")
    case = ready(store)
    store.record_independent_check(case.case_id, case.revision_id, action())
    confirmed = store.get_case(case.case_id)
    payload = CaseInputs(
        sources=case.snapshot.sources, evidence=case.snapshot.evidence
    ).model_dump()
    source_id = uuid4()
    text = payload["sources"][0]["text"] + "\nSynthetic revised document."
    payload["sources"][0].update(
        source_id=source_id, text=text, sha256=sha256(text.encode()).hexdigest()
    )
    payload["evidence"]["source_ids"] = (source_id,)
    payload["evidence"]["extraction"]["attempt_id"] = uuid4()
    payload["evidence"]["account_identifier"]["candidates"][0]["evidence"]["source_id"] = source_id
    changed = store.replace_inputs(
        case.case_id,
        confirmed.revision_id,
        CaseInputs.model_validate(payload),
        operator_id="operator",
    )
    assert (
        changed.snapshot.review
        is changed.snapshot.comparison
        is changed.snapshot.verification
        is None
    )
    assert changed.independent_verification_status == "NOT_VERIFIED"
    assert store.get_case(case.case_id, confirmed.revision_id).snapshot.verification is not None
    assert (
        store.get_case(case.case_id, confirmed.revision_id).independent_verification_status
        == "STALE"
    )
    assert len(store.verification_events(case.case_id)) == 1


def test_case_creation_rejects_baseline_changed_during_extraction(tmp_path: Path):
    store = SQLiteStore(tmp_path / "db")
    vendor, data = inputs()
    store.put_vendor(vendor, operator_id="operator")
    updated = TrustedVendorRecord.model_validate(vendor.model_dump() | {"revision_id": uuid4()})
    store.put_vendor(updated, operator_id="operator", expected_revision_id=vendor.revision_id)
    with pytest.raises(WorkflowError, match="during extraction"):
        store.create_case(
            data,
            vendor.vendor_id,
            operator_id="operator",
            expected_vendor_revision_id=vendor.revision_id,
        )
    assert store.db.execute("SELECT COUNT(*) FROM case_heads").fetchone()[0] == 0


def test_raw_text_failure_is_durable_not_reviewable(tmp_path: Path, monkeypatch, capsys):
    from payproof.workflow_cli import main

    monkeypatch.setenv("PAYPROOF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PAYPROOF_EXTRACTION_MODE", "disabled")
    store = SQLiteStore(tmp_path / "payproof.sqlite3")
    vendor, _ = inputs()
    store.put_vendor(vendor, operator_id="operator")
    source = tmp_path / "synthetic-email.txt"
    source.write_text("Synthetic invoice: payment details to follow.")
    assert (
        main(
            [
                "case-create",
                "--vendor-id",
                str(vendor.vendor_id),
                "--text",
                str(source),
                "--operator",
                "operator",
            ]
        )
        == 0
    )
    metadata = json.loads(capsys.readouterr().out.splitlines()[0])
    from uuid import UUID

    case = store.get_case(UUID(metadata["case_id"]))
    assert case.snapshot.sources[0].text == source.read_text()
    assert case.snapshot.evidence.extraction.failure_code == "NOT_CONFIGURED"
    with pytest.raises(ValueError, match="failed extraction"):
        store.review(
            case.case_id,
            case.revision_id,
            operator_id="operator",
            destination_instructions_checked=True,
        )
    case = store.compare(case.case_id, case.revision_id, operator_id="operator")
    assert case.snapshot.comparison.state == "UNCERTAIN"


def test_json_import_rejects_duplicate_keys(tmp_path: Path, monkeypatch):
    from payproof.workflow_cli import main

    monkeypatch.setenv("PAYPROOF_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PAYPROOF_EXTRACTION_MODE", "disabled")
    vendor, _ = inputs()
    payload = vendor.model_dump_json()
    path = tmp_path / "vendor.json"
    path.write_text(payload[:-1] + ',"canonical_vendor_name":"overwritten"}')
    assert main(["vendor-add", "--file", str(path), "--operator", "operator"]) == 2
    store = SQLiteStore(tmp_path / "data/payproof.sqlite3")
    assert store.db.execute("SELECT COUNT(*) FROM vendor_heads").fetchone()[0] == 0


def test_version_number_alone_does_not_prove_initialization(tmp_path: Path):
    path = tmp_path / "db"
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version=1")
    db.close()
    with pytest.raises(WorkflowError, match="incomplete"):
        SQLiteStore(path)
