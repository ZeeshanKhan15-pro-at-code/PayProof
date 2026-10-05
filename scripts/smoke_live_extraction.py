"""One synthetic live smoke using only process environment; no key arguments/files."""

import json
import os

from payproof.config import ConfigurationError, load_settings
from payproof.documents import capture_text
from payproof.extraction import ExtractionInputError, extract_attempt

EMAIL = "From: billing@synthetic.example\nVendor: Synthetic Live Smoke Supplies\nPlease use the attached invoice payment instructions."
INVOICE = "Vendor: Synthetic Live Smoke Supplies\nInvoice: LIVE-SMOKE-001\nAmount: 1250.00 GBP\nBank: Synthetic Demo Bank\nPlease pay to IBAN GB57TEST00000000009928."


def main() -> int:
    if (
        os.environ.get("PAYPROOF_EXTRACTION_MODE") != "live"
        or not os.environ.get("PAYPROOF_PROVIDER_API_KEY", "").strip()
        or not os.environ.get("PAYPROOF_PROVIDER_MODEL", "").strip()
    ):
        print(json.dumps({"status": "NOT_CONFIGURED", "provider_called": False}))
        return 2
    try:
        settings = load_settings(os.environ)
        sources = (
            capture_text(EMAIL, kind="EMAIL", operator_id="synthetic-live-smoke"),
            capture_text(INVOICE, kind="INVOICE", operator_id="synthetic-live-smoke"),
        )
        attempt = extract_attempt(sources, settings=settings)
    except (ConfigurationError, ExtractionInputError):
        print(json.dumps({"status": "INVALID_CONFIGURATION_OR_INPUT", "provider_called": False}))
        return 1
    evidence = attempt.evidence
    failure = evidence.extraction.failure_code
    accounts = tuple(candidate.value for candidate in evidence.account_identifier.candidates)
    matches = (
        failure is None
        and evidence.account_identifier.status == "FOUND"
        and accounts == ("GB57TEST00000000009928",)
        and evidence.reply_to.status == "MISSING"
        and evidence.routing_identifier.status == "MISSING"
        and evidence.claims_details_changed.status == "MISSING"
    )
    print(
        json.dumps(
            {
                "status": "FAILED" if failure else "PASS" if matches else "SMOKE_MISMATCH",
                "failure_code": failure,
                "provider_called": True,
                "provider": evidence.extraction.provider,
                "model": evidence.extraction.model,
                "evidence": evidence.model_dump(mode="json"),
            }
        )
    )
    return 0 if matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
