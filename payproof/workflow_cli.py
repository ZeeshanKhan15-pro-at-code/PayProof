"""Local human-operated durable workflow; never exposed as an unauthenticated API."""

import argparse
import json
import os
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError

from payproof.config import load_settings
from payproof.presentation import render_evidence, render_result
from payproof.schemas import TrustedVendorRecord
from payproof.secret_guard import reject_configured_secrets
from payproof.storage import SQLiteStore, WorkflowError
from payproof.validation import parse_contract
from payproof.workflow_contracts import CaseInputs, IndependentCheckAction, StoredCase


def read_input(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(4_194_305)
    if len(raw) > 4_194_304:
        raise WorkflowError("JSON import exceeds 4 MiB")
    return raw


def display(case: StoredCase) -> None:
    print(
        json.dumps(
            {
                "case_id": str(case.case_id),
                "revision_id": str(case.revision_id),
                "version": case.version,
                "stale": case.stale,
                "independent_verification_status": case.independent_verification_status,
            }
        )
    )
    print(render_evidence(case.snapshot))
    if case.snapshot.comparison:
        print(render_result(case.snapshot))
    if case.snapshot.verification:
        print(case.snapshot.verification.model_dump_json(indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Private local SQLite workflow (human-operated)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    vendor = commands.add_parser("vendor-add")
    vendor.add_argument("--file", type=Path, required=True)
    vendor.add_argument("--operator", required=True)
    vendor.add_argument("--expected-revision", type=UUID)
    create = commands.add_parser(
        "case-import", help="Import source-bound CaseInputs only; no review/comparison/confirmation"
    )
    create.add_argument("--file", type=Path, required=True)
    create.add_argument("--vendor-id", type=UUID, required=True)
    create.add_argument("--operator", required=True)
    extract = commands.add_parser(
        "case-create", help="Capture text and use configured extraction; no automatic human review"
    )
    extract.add_argument("--vendor-id", type=UUID, required=True)
    extract.add_argument("--operator", required=True)
    extract.add_argument("--text", type=Path, action="append", default=[])
    extract.add_argument("--email", type=Path, action="append", default=[])
    extract.add_argument("--invoice", type=Path, action="append", default=[])
    for name in ("show", "events", "replace", "refresh", "review", "compare", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--case-id", type=UUID, required=True)
        if name not in ("show", "events"):
            command.add_argument("--revision-id", type=UUID, required=True)
            command.add_argument("--operator", required=True)
        if name == "replace":
            command.add_argument("--file", type=Path, required=True)
        if name == "verify":
            command.add_argument("--action-id", type=UUID)
    args = parser.parse_args(argv)
    store = None
    try:
        settings = load_settings(os.environ)
        reject_configured_secrets(vars(args), settings)

        def show(case: StoredCase) -> None:
            reject_configured_secrets(case.model_dump(mode="json"), settings)
            display(case)

        store = SQLiteStore(settings.data_dir / "payproof.sqlite3")
        if args.command == "init":
            print("SQLite schema version 1 initialized.")
        elif args.command == "vendor-add":
            record = parse_contract(TrustedVendorRecord, read_input(args.file))
            reject_configured_secrets(record.model_dump(mode="json"), settings)
            store.put_vendor(
                record, operator_id=args.operator, expected_revision_id=args.expected_revision
            )
            print("Trusted vendor revision stored.")
        elif args.command == "case-create":
            from payproof.cases import start_case
            from payproof.cli import _capture_files

            extraction_baseline = store.get_vendor(args.vendor_id)
            sources = _capture_files(
                (("PLAIN_TEXT", args.text), ("EMAIL", args.email), ("INVOICE", args.invoice)),
                args.operator,
            )
            reject_configured_secrets(tuple(s.model_dump(mode="json") for s in sources), settings)
            snapshot = start_case(extraction_baseline, sources, settings=settings)
            reject_configured_secrets(snapshot.model_dump(mode="json"), settings)
            show(
                store.create_case(
                    CaseInputs(sources=snapshot.sources, evidence=snapshot.evidence),
                    args.vendor_id,
                    operator_id=args.operator,
                    expected_vendor_revision_id=extraction_baseline.revision_id,
                )
            )
        elif args.command == "case-import":
            data = parse_contract(CaseInputs, read_input(args.file))
            reject_configured_secrets(data.model_dump(mode="json"), settings)
            show(store.create_case(data, args.vendor_id, operator_id=args.operator))
        elif args.command == "show":
            show(store.get_case(args.case_id))
        elif args.command == "events":
            for event in store.verification_events(args.case_id):
                reject_configured_secrets(event.model_dump(mode="json"), settings)
                print(event.model_dump_json(indent=2))
        elif args.command in ("replace", "refresh"):
            current = store.get_case(args.case_id)
            data = (
                parse_contract(CaseInputs, read_input(args.file))
                if args.command == "replace"
                else CaseInputs(
                    sources=current.snapshot.sources, evidence=current.snapshot.evidence
                )
            )
            reject_configured_secrets(data.model_dump(mode="json"), settings)
            show(
                store.replace_inputs(
                    args.case_id, args.revision_id, data, operator_id=args.operator
                )
            )
        elif args.command == "review":
            current = store.get_case(args.case_id)
            show(current)
            if (
                input("After reading every source and competing destination, type REVIEWED: ")
                != "REVIEWED"
            ):
                print("No review recorded.")
                return 1
            show(
                store.review(
                    args.case_id,
                    args.revision_id,
                    operator_id=args.operator,
                    destination_instructions_checked=True,
                )
            )
        elif args.command == "compare":
            show(store.compare(args.case_id, args.revision_id, operator_id=args.operator))
        elif args.command == "verify":
            current = store.get_case(args.case_id)
            show(current)
            baseline = current.snapshot.baseline
            result = current.snapshot.comparison
            if (
                current.stale
                or current.revision_id != args.revision_id
                or not baseline
                or not current.snapshot.review
                or not result
                or result.state == "UNCERTAIN"
            ):
                raise ValueError("fresh reviewed decisive comparison required")
            print(
                "Use ONLY this previously trusted contact; confirm the exact full destination instructions independently:"
            )
            print(baseline.callback_contact.model_dump_json(indent=2))
            print(
                result.requested_identity.model_dump_json(indent=2)
                if result.requested_identity
                else "Missing destination"
            )
            person = input("Independently reached person/role: ").strip() or None
            outcome = input("Outcome (CONFIRMED / NOT_CONFIRMED / INCONCLUSIVE): ")
            notes = input("Optional notes: ").strip() or None
            if (
                input(
                    "Type RECORD INDEPENDENT CHECK to attest you independently used the displayed trusted contact: "
                )
                != "RECORD INDEPENDENT CHECK"
            ):
                print("No independent check recorded.")
                return 1
            action = IndependentCheckAction.model_validate(
                {
                    "action_id": args.action_id or uuid4(),
                    "operator_id": args.operator,
                    "independently_checked": True,
                    "what_was_checked": "EXACT_PAYMENT_DESTINATION_INSTRUCTIONS",
                    "outcome": outcome,
                    "independently_reached_person": person,
                    "notes": notes,
                }
            )
            reject_configured_secrets(action.model_dump(mode="json"), settings)
            print(
                store.record_independent_check(
                    args.case_id, args.revision_id, action
                ).model_dump_json(indent=2)
            )
            show(store.get_case(args.case_id))
        return 0
    except WorkflowError as exc:
        print(f"Workflow rejected: {exc}")
        return 2
    except (ValueError, ValidationError, OSError, sqlite3.Error, EOFError):
        # Never echo exception bodies: validators/DB errors can embed input secrets.
        print(
            "Workflow failed safely: invalid input/configuration, stale revision, cancelled input, or storage failure. No success is claimed."
        )
        return 2
    finally:
        if store:
            store.close()
