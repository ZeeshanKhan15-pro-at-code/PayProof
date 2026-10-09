# Optional synthetic examples and provider-independent replay

The public primary action remains **VERIFY A PAYMENT REQUEST** → deliberately establish a trusted baseline → supply the new request. **Try an example** is a secondary area linking to `/workspace/examples`; no example selection is required for own-data use.

The catalog is machine-readable at `payproof/fixtures/demo_proof/public_examples.json` and validated in `payproof/demo_examples.py`. The original five-case proof corpus and frozen benchmark evidence/labels are unchanged. All six examples retain canonical source text, evidence spans, a fictional trusted baseline and explicitly fixture-attributed observations:

| Example payment request | Expected comparison after review | Purpose |
| --- | --- | --- |
| Destination changed | VERIFY / DESTINATION_CHANGED | Acme trusted 3821 → requested 9928 |
| Destination unchanged | UNCHANGED / DESTINATION_MATCH | Supported equality; no payment authorization |
| Ambiguous/conflicting destination | UNCERTAIN / DESTINATION_AMBIGUOUS | Both competing accounts remain visible |
| Missing payment information | UNCERTAIN / DESTINATION_MISSING | Absence cannot establish equality |
| Extraction/provider unavailable | UNCERTAIN / EXTRACTION_FAILED | Explicitly simulated PROVIDER_UNAVAILABLE replay; source inventory also identifies incomplete observations |
| Indirect instruction asking for a forbidden verdict | VERIFY / DESTINATION_CHANGED | Quoted source asks for VERIFIED/approval; replay retains only canonical extracted observations |

Expected labels appear only as preview expectations. Opening an example persists sources and observations; it assigns no comparison, source review or independent verification. The operator must explicitly review successful observations and run the existing deterministic comparison. A failed extraction cannot receive a successful source-review acknowledgment or human confirmation. No example creates an independent-verification event.

## Separation from live extraction

Every preview, replay case and fixture receipt is visibly **SYNTHETIC DEMONSTRATION**, and never labeled LIVE. Observations are saved FIXTURE data, including the deliberately simulated failure record. Opening/reading/comparing examples does not invoke any extraction function, provider, live rate allowance or API budget reservation. This is replay of synthetic observations followed by the real comparison engine, not a live AI accuracy claim.

An own-data request uses its configured live path even if its text exactly matches an example. TIMEOUT, PROVIDER_UNAVAILABLE and invalid/forbidden output remain explicit live failures with no supported observations. There is no fixture fallback. Once compared, the failed case is UNCERTAIN and cannot receive human confirmation. An exhausted live allowance also remains an explicit error. The user may separately choose a synthetic example; opening it never replaces or changes the failed own-data case.

The indirect-instruction example does **not** prove that a live model resisted prompt injection. Its saved observations demonstrate the permitted extraction contract and deterministic/human state boundary. Mocked live responses containing a forbidden verdict are separately rejected by strict schema validation. These tests are not live provider evaluation.

Each preview issues a new submission identifier. Identical POST retries return the same case; conflicting reuse is rejected. A fresh launch namespaces its case, evidence and fictional vendor/contact IDs, so edits to earlier examples or genuine user records cannot silently alter or be overwritten by a new demonstration. Twelve new launches/session/minute bound sample creation independently of live calls. Cases remain in the existing temporary isolated public store and follow its expiration/isolation/history rules.

Retry extraction or source replacement on an already opened case remains the explicitly configured extraction path. It is not replay and may call the live provider when enabled. To repeat an outage-independent demonstration, open a fresh optional example from the gallery; its replay is separate and requires no provider configuration. Synthetic source labels remain retained even if the user later deliberately runs actual live extraction on that source.

## Verification

`tests/test_demo_examples.py` covers all six through real mounted Flask/SQLite creation, explicit review and deterministic comparison; strict catalog grounding; no invented review/verification; unknown/tampered IDs; CSRF and session isolation; submission idempotency; revised-baseline/history preservation; and all examples functioning after a mocked live timeout/provider failure/forbidden output consumes the global live allowance. Installed-wheel smoke loads the packaged catalog and serves/opens the gallery/sample outside the checkout.

```bash
.venv/bin/python -m pytest -q tests/test_demo_examples.py tests/test_public_workspace.py
.venv/bin/python scripts/verify_foundation.py /tmp/payproof-example-verification-new-run
make serve
# Browser: open the secondary Try an example link, inspect source, open sample,
# acknowledge source review where available, then run deterministic comparison.
```

Only synthetic fixtures and mocked provider failures are used by these verification commands. No live success, real callback, public deployment or human usability certification is claimed. Existing gold benchmark failures and provider-access uncertainty remain separate gates; examples do not repair or conceal them.

Actual verification on 2026-10-09: **807 tests PASS**; lint, formatting, strict typecheck (41 source files), configuration, frozen protocol, build and installed-package smoke PASS. Gold diagnostic remains FAIL at28/30 states; held-out gold remains FAIL at56/72 states and53/72 exact; both retain0 critical false UNCHANGED. No live extraction benchmark was run. Fresh evidence: `/tmp/payproof-demo-fallback-20261009/gates.json` and its benchmark subdirectories, with output at `/tmp/payproof-demo-fallback-20261009.log`. Chrome local visual preview was BLOCKED by `ERR_BLOCKED_BY_CLIENT`; no browser protections were changed. Application HTML rendering and installed-package gallery/sample checks passed.
