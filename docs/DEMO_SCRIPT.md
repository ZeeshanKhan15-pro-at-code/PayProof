# PayProof evidence demonstration (2–4 minutes)

This demonstration proves a narrow mechanism: source-backed destination comparison against a previously trusted vendor record, followed by a separate human action. It does not demonstrate live model accuracy, real callback completion, account ownership or payment authorization.

## Prepare once, before presenting

From the repository root with the documented pinned environment installed:

```bash
.venv/bin/python -m payproof.demo_proof \
  --output /tmp/payproof-proof-run-001 \
  --seed-data-dir data/acme-demo-run-001
export PAYPROOF_DATA_DIR="$PWD/data/acme-demo-run-001"
make serve
```

Both directories must be new. Existing outputs/data are refused, preserving the first run and avoiding damage to real cases. Set the existing `PAYPROOF_SECRET_KEY` and separate `PAYPROOF_OPERATOR_TOKEN` privately in the launching environment before `make serve`; the generator needs neither credential. Do not put secrets in the script, source, command history or screenshots. Configuration is not loaded from `.env` automatically. See [WEB_WORKFLOW.md](WEB_WORKFLOW.md).

Open `/tmp/payproof-proof-run-001/report.html` directly in a browser and `http://127.0.0.1:8000/operator`. Log in once offscreen. The generated report links to the five seeded case IDs on the local server. Those SQLite cases initially have **no source review, comparison or independent confirmation**. The report's comparison snapshots use **SIMULATED_DEMO_SOURCE_REVIEW**, confined to the static proof; they do not record operator review in SQLite. These are explicitly authored FIXTURE observations, not an AI response or live-mode fallback. The failure example actually executes disabled extraction and saves `NOT_CONFIGURED`.

For report-only use, omit `--seed-data-dir`, or run `make demo-proof OUTPUT=/tmp/payproof-proof-run-002`. The committed [report](../benchmarks/demo-proof-v1/report.html) and [full inputs/outcomes](../benchmarks/demo-proof-v1/proof.json) are usable without a server. Actual TCP binding remains subject to the host: this execution sandbox prohibits socket creation; Flask integration tests validate the workflow, not a running listener.

## Present

**0:00–0:25 — Problem and plausible context.** “The invoice can look familiar while the payment destination changes. PayProof compares the request to information previously trusted by a human.” Open the report's **changed** operator link. Show the original Acme email: same sender/reply-to domain, vendor, invoice `ACME-001`, amount and bank context as the unchanged control. Its treasury-update explanation is untrusted source text, not a finding about intent.

**0:25–1:10 — Hidden change and evidence.** Show full trusted `GB46TEST00000000003821` and new `GB57TEST00000000009928`. Endings 3821/9928 are presentation aids; equality uses complete canonical identifiers. Point to old origin `synthetic-onboarding/acme-proof-3821`, recorded before source capture. Point to the exact new instruction quote, source UUID, character range and source hash. Inspect the entire original text and independent inventory, then explicitly acknowledge **source review only**. No independent verification has occurred.

**1:10–1:40 — Deterministic gate and human responsibility.** Click **Run deterministic comparison**: `VERIFY / DESTINATION_CHANGED`. Show the field difference and previously trusted callback `+1-202-555-0182`, from the frozen vendor record, not the request. “This requires an independent human check of the exact instructions. The model cannot confirm this.” Point to the separate, unchecked independent-check form and `Human attestation: NOT_VERIFIED`; leave it unsubmitted. The callback is fictional: **do not call it**. A separate explicitly labeled synthetic role-play may submit a human outcome with simulation notes; that event does not change comparison `VERIFY` and is not proof of a real call. Automated integration tests exercise this separation.

**1:40–2:20 — Controls and fail-closed behavior.** Use the generated report's other outcomes (or inspect/review/compare their operator cases):

| Case | Demonstrated behavior |
| --- | --- |
| `unchanged` | Supported reviewed full destination equals baseline: `UNCHANGED / DESTINATION_MATCH`; destination equality only. |
| `conflicting` | Two competing instructions retained: `UNCERTAIN / DESTINATION_AMBIGUOUS`. |
| `extraction-failure` | Actual disabled extraction: `NOT_CONFIGURED`, then `UNCERTAIN / EXTRACTION_FAILED`. Successful review and human confirmation unavailable. This is a configuration failure, not a live timeout test. |
| `historical-omission` | Source says “our old account was” 3821, followed by current 9928. Deliberately deficient fixture observes only old 3821. Independent inventory exposes 9928 as **NOT OBSERVED BY EXTRACTION**; even a simulated broad review cannot turn this into `UNCHANGED`. Result: `UNCERTAIN / DESTINATION_AMBIGUOUS`. |

**2:20–3:15 — Benchmark proof, with honest boundaries.** Scroll to the separately labeled gold, live extraction and live end-to-end sections. Every displayed metric comes from the saved run embedded in `proof.json`; the report identifies original artifact paths, SHA-256 digests, run date and corpus hash. Current saved gold comparison: **56/72 states**, **53/72 exact results**, **12/24 changed destinations detected**, **12 changed destinations abstained**, **zero critical false UNCHANGED**, **zero false VERIFY**. Strict uncertainty handling is **30/33**; state-only uncertainty recall is **33/33**, with reason mismatches kept visible. Overall gold status is **FAIL**, with every failing case listed. Do not present the separate unreviewed gate's state score as overall accuracy.

“Live extraction is BLOCKED / NOT_CONFIGURED; live end-to-end accuracy is NOT_MEASURED. No model calls completed in this saved attempt. The synthetic walkthrough is not held-out extraction performance.” Gold results come from [the retained red-team after-run](../benchmarks/phase2-redteam/after-gold/report.json); the live status comes from [the saved blocked attempt](../benchmarks/phase2-redteam/live-attempt.json). Do not substitute a fixture success for live results or hide changed-case abstentions behind zero critical misses.

**3:15–3:35 — Limitations.** “This is synthetic proof, with independent benchmark label review pending. Comparison supports checksum-valid full GB/DE IBANs. Multiple plausible instructions deliberately abstain; discovery and AI extraction are not exhaustive. Human checks are self-reported, revision-bound records. No payments or bank ownership verification occur.” Phase 3 owns presentation polish.

## Reproduce and inspect

Canonical demo definition: [acme.json](../payproof/fixtures/demo_proof/acme.json), separate from the frozen held-out corpus. Expected states/reasons were written before this demonstration run. The runner checks each outcome, validates exact source grounding with existing contracts, records the actual failure path and preserves all snapshots. A demo exit 0 means only those curated mechanism checks passed; it does **not** mean the saved gold benchmark passed.

```bash
.venv/bin/python -m pytest -q tests/test_demo_proof.py
.venv/bin/python -m payproof.demo_proof --output /tmp/payproof-proof-run-003
# Frozen benchmark definitions/protocol validation; no provider or new scores:
.venv/bin/python -m payproof.heldout_benchmark
```

Missing, malformed or internally inconsistent benchmark artifacts reject report generation; there is no hard-coded metric fallback. Output directories are never silently overwritten. IDs are stable across demo seeds; run timestamps and event UUIDs vary, while the declared inputs and expected states remain fixed. Operator history records actual clicks; independent confirmation is never generated by the proof runner or seed command.

## Verification for this change

2026-10-07: Ruff lint/format passed; mypy passed for 34 source files; the full suite passed **754 tests**, including ten new demo/report/operator instances. Frozen held-out definition/protocol validation passed without changing labels or running a provider. The synthetic proof passed and retained zero independent confirmations. Both embedded benchmark artifact digests match their original files. Wheel/sdist build and installed-package smoke passed outside the checkout, including loading the packaged Acme definitions and executing all five mechanism paths, SQLite migration/restart, gated pages and assets. Actual TCP binding was not retested; no live extraction or real callback was attempted.
