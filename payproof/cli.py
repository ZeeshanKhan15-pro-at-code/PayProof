"""Minimal offline/debug interface. Errors do not echo source or settings values."""

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from pydantic import ValidationError

from payproof.benchmark import validate_corpus
from payproof.cases import complete_case, review_case, start_case
from payproof.config import ConfigurationError, Settings, load_settings
from payproof.documents import capture_text
from payproof.extraction import extract_documents
from payproof.fixtures import load_corpus
from payproof.presentation import render_evidence, render_result
from payproof.schemas import SourceDocument, SourceKind, TrustedVendorRecord
from payproof.validation import parse_contract
from payproof.web import create_app


def _capture_files(
    groups: tuple[tuple[SourceKind, list[Path]], ...], operator_id: str
) -> tuple[SourceDocument, ...]:
    if sum(len(paths) for _, paths in groups) > 16:
        raise ValueError("too many sources")
    sources: list[SourceDocument] = []
    for kind, paths in groups:
        for path in paths:
            with path.open("rb") as stream:
                raw = stream.read(80_001)
            if len(raw) > 80_000:
                raise ValueError("source too large")
            sources.append(
                capture_text(
                    raw.decode("utf-8"), operator_id=operator_id, kind=kind, label=path.name
                )
            )
    return tuple(sources)


def _run_workflow(
    baseline: TrustedVendorRecord,
    sources: tuple[SourceDocument, ...],
    *,
    settings: Settings,
    operator_id: str,
    no_review: bool,
    simulate_review: bool,
) -> int:
    case = start_case(baseline, sources, settings=settings)
    print(render_evidence(case))
    if simulate_review:
        print("\nSIMULATED SOURCE REVIEW: synthetic demo only; no human attestation.")
    acknowledged = False
    if not case.evidence.extraction.failure_code and not no_review:
        if simulate_review:
            acknowledged = True
        else:
            try:
                answer = input(
                    "\nCheck all original source text and evidence above for complete current "
                    "payment instructions. Type REVIEWED to acknowledge source review, "
                    "or press Enter to leave it unresolved: "
                )
            except EOFError:
                answer = ""
            acknowledged = answer.strip() == "REVIEWED"
    if acknowledged:
        case = review_case(case, operator_id=operator_id, destination_instructions_checked=True)
    case = complete_case(case)
    print("\n" + render_result(case))
    assert case.comparison is not None
    return 2 if case.comparison.state == "UNCERTAIN" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PayProof source-bound payment destination review")
    parser.add_argument(
        "command", choices=("check", "debug", "benchmark", "serve", "extract", "analyze", "demo")
    )
    parser.add_argument(
        "--email", type=Path, action="append", default=[], help="UTF-8 plain-text email file"
    )
    parser.add_argument(
        "--invoice", type=Path, action="append", default=[], help="UTF-8 plain-text invoice file"
    )
    parser.add_argument(
        "--text", type=Path, action="append", default=[], help="UTF-8 plain-text source file"
    )
    parser.add_argument("--vendor", type=Path, help="TrustedVendorRecord JSON for analyze")
    parser.add_argument("--operator", help="Local source-review operator name for analyze/demo")
    review_options = parser.add_mutually_exclusive_group()
    review_options.add_argument(
        "--no-review", action="store_true", help="Do not prompt or record source review"
    )
    review_options.add_argument(
        "--simulate-review", action="store_true", help="Synthetic demo smoke test only"
    )
    args = parser.parse_args(argv)
    if args.command not in ("extract", "analyze") and (args.email or args.invoice or args.text):
        parser.error("document flags require extract or analyze")
    if args.command in ("extract", "analyze") and not (args.email or args.invoice or args.text):
        parser.error("extract/analyze requires --email, --invoice, or --text")
    if args.command == "analyze" and args.vendor is None:
        parser.error("analyze requires --vendor")
    if args.command != "analyze" and args.vendor is not None:
        parser.error("--vendor requires analyze; demo uses its seeded trusted vendor")
    if args.command not in ("analyze", "demo") and (args.operator or args.no_review):
        parser.error("--operator/--no-review require analyze or demo")
    if args.simulate_review and args.command != "demo":
        parser.error("--simulate-review is allowed only for the seeded synthetic demo")
    try:
        # The explicit synthetic demo never uses live settings or provider credentials.
        settings = load_settings(
            {"PAYPROOF_EXTRACTION_MODE": "fixture"} if args.command == "demo" else os.environ
        )
        if args.command == "demo":
            corpus = load_corpus()
            seed = next(r for r in corpus.requests if r.fixture_id == "demo-account-change")
            demo_baseline = next(
                v for v in corpus.vendors if v.revision_id == seed.baseline_revision_id
            )
            operator = (
                "synthetic-demo-review-simulation"
                if args.simulate_review
                else args.operator or "synthetic-demo-operator"
            )
            print("PayProof SYNTHETIC DEMO: trusted account ending 3821 -> requested ending 9928")
            print("Fixture inputs and contacts are fictional. Extraction is offline.")
            source = capture_text(
                seed.source.text,
                operator_id=operator,
                kind=seed.source.kind,
                label=seed.source.label,
            )
            return _run_workflow(
                demo_baseline,
                (source,),
                settings=settings,
                operator_id=operator,
                no_review=args.no_review,
                simulate_review=args.simulate_review,
            )
        if args.command in ("extract", "analyze"):
            operator = args.operator or "local-cli-operator"
            baseline: TrustedVendorRecord | None = None
            if args.command == "analyze":
                with args.vendor.open("rb") as stream:
                    raw_vendor = stream.read(64_001)
                if len(raw_vendor) > 64_000:
                    raise ValueError("vendor record exceeds input limit")
                baseline = parse_contract(TrustedVendorRecord, raw_vendor)
            groups: tuple[tuple[SourceKind, list[Path]], ...] = (
                ("EMAIL", args.email),
                ("INVOICE", args.invoice),
                ("PLAIN_TEXT", args.text),
            )
            sources = _capture_files(groups, operator)
            if args.command == "analyze":
                assert baseline is not None
                print(f"Selected trusted vendor record: {json.dumps(str(args.vendor))}")
                return _run_workflow(
                    baseline,
                    sources,
                    settings=settings,
                    operator_id=operator,
                    no_review=args.no_review,
                    simulate_review=False,
                )
            evidence = extract_documents(sources, settings=settings)
            print(evidence.model_dump_json(indent=2))
            return 2 if evidence.extraction.failure_code else 0
        if args.command == "serve":
            app = create_app(settings)
            app.run(host="127.0.0.1", port=settings.port, debug=False, use_reloader=False)
            return 0
        if args.command == "benchmark":
            report = validate_corpus()
            print(json.dumps(asdict(report), indent=2))
            return 0 if report.comparison_evaluation == "PASS" else 1
        corpus = load_corpus()
        if args.command == "debug":
            print(
                json.dumps(
                    {
                        "stage": "skeleton",
                        "extraction_mode": settings.extraction_mode,
                        "synthetic_vendors": [v.canonical_vendor_name for v in corpus.vendors],
                        "synthetic_requests": [r.fixture_id for r in corpus.requests],
                        "decision_engine": "iban-gb-de-v1",
                        "verification": "NOT_IMPLEMENTED",
                    },
                    indent=2,
                )
            )
            return 0
        response = create_app(settings).test_client().get("/healthz")
        if response.status_code != 200:
            raise ValueError("application initialization failed")
        print(
            json.dumps(
                {
                    "status": "initialized",
                    "stage": "skeleton",
                    "trusted_vendor_fixtures": len(corpus.vendors),
                    "request_fixtures": len(corpus.requests),
                    "database_created": False,
                    "provider_called": False,
                }
            )
        )
        return 0
    except ConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
    except (ValidationError, ValueError, OSError):
        print(
            "Operation failed: invalid or unavailable input/application data",
            file=sys.stderr,
        )
    return 1
