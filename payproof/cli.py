"""Minimal offline/debug interface. Errors do not echo source or settings values."""

import argparse
import json
import os
import sys
from dataclasses import asdict

from pydantic import ValidationError

from payproof.benchmark import validate_corpus
from payproof.config import ConfigurationError, load_settings
from payproof.fixtures import load_corpus
from payproof.web import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PayProof Phase-1 repository skeleton")
    parser.add_argument("command", choices=("check", "debug", "benchmark", "serve"))
    args = parser.parse_args(argv)
    try:
        settings = load_settings(os.environ)
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
            "Initialization failed: invalid or unavailable fixture/application data",
            file=sys.stderr,
        )
    return 1
