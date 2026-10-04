"""Minimal offline/debug interface. Errors do not echo source or settings values."""

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from pydantic import ValidationError

from payproof.benchmark import validate_corpus
from payproof.config import ConfigurationError, load_settings
from payproof.documents import capture_text
from payproof.extraction import extract_documents
from payproof.fixtures import load_corpus
from payproof.schemas import SourceDocument, SourceKind
from payproof.web import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PayProof Phase-1 repository skeleton")
    parser.add_argument("command", choices=("check", "debug", "benchmark", "serve", "extract"))
    parser.add_argument(
        "--email", type=Path, action="append", default=[], help="UTF-8 plain-text email file"
    )
    parser.add_argument(
        "--invoice", type=Path, action="append", default=[], help="UTF-8 plain-text invoice file"
    )
    parser.add_argument(
        "--text", type=Path, action="append", default=[], help="UTF-8 plain-text source file"
    )
    args = parser.parse_args(argv)
    if args.command != "extract" and (args.email or args.invoice or args.text):
        parser.error("document flags require the extract command")
    if args.command == "extract" and not (args.email or args.invoice or args.text):
        parser.error("extract requires --email, --invoice, or --text")
    try:
        settings = load_settings(os.environ)
        if args.command == "extract":
            sources: list[SourceDocument] = []
            groups: tuple[tuple[SourceKind, list[Path]], ...] = (
                ("EMAIL", args.email),
                ("INVOICE", args.invoice),
                ("PLAIN_TEXT", args.text),
            )
            if sum(len(paths) for _, paths in groups) > 16:
                raise ValueError("too many sources")
            for kind, paths in groups:
                for path in paths:
                    with path.open("rb") as stream:
                        raw = stream.read(80_001)
                    if len(raw) > 80_000:
                        raise ValueError("source too large")
                    sources.append(
                        capture_text(
                            raw.decode("utf-8"),
                            operator_id="cli-operator",
                            kind=kind,
                            label=path.name,
                        )
                    )
            evidence = extract_documents(tuple(sources), settings=settings)
            print(evidence.model_dump_json(indent=2))
            return 2 if evidence.extraction.failure_code else 0
        if args.command == "serve":
            app = create_app(settings)
            app.run(host="127.0.0.1", port=settings.port, debug=False, use_reloader=False)
            return 0
        if args.command == "benchmark":
            print(json.dumps(asdict(validate_corpus()), indent=2))
            return 0
        corpus = load_corpus()
        if args.command == "debug":
            print(
                json.dumps(
                    {
                        "stage": "skeleton",
                        "extraction_mode": settings.extraction_mode,
                        "synthetic_vendors": [v.canonical_vendor_name for v in corpus.vendors],
                        "synthetic_requests": [r.fixture_id for r in corpus.requests],
                        "decision_engine": "NOT_IMPLEMENTED",
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
