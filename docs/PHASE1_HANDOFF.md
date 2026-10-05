# Phase-1 handoff

## Freeze decision

Freeze the existing local CLI core, without new product features or changed comparison rules. It proves the synthetic payment-change mechanism without UI polish. **Full Phase-1 release sign-off remains pending:** clean installation was blocked by this environment, historical credential revocation is unconfirmed, and the architecture's persistent verification workflow and 36-case release evaluation are unfinished. Do not describe this repository as an operational payment-verification service.

The [architecture](ARCHITECTURE.md) remains the frozen target, not a claim that every component is implemented. The [data model](DATA_MODEL.md), [workflow](VERTICAL_SLICE.md), [comparison](COMPARISON.md), [benchmark specification](BENCHMARK_SPEC.md) and [red-team report](PHASE1_REDTEAM.md) describe the implemented subset and its limits. This closing pass changes documentation and refreshes measured gold results; no new application capability is added.

## What works

- Explicit vendor selection and strict validation of a previously trusted baseline/contact revision.
- Bounded UTF-8 text ingestion, immutable source snapshots, SHA-256 binding, exact evidence quotes/offsets and complete account-token grounding.
- Schema-constrained extraction adapter, explicit offline synthetic fixtures, canonical failures for disabled/malformed/failed extraction, and no model-generated verdict or human confirmation.
- Full original/evidence display before explicit source review. Comparison remains unresolved before review; the offline review simulation is confined to the fixed demo.
- Conservative GB/DE IBAN normalization, full identifier equality, deterministic `UNCHANGED`, `VERIFY`, `UNCERTAIN`, machine-readable reasons and callback guidance.
- Adversarial regression coverage, reproducible gold benchmark, saved per-case results, replay and distributable package smoke validation.
- Local CLI and read-only Flask initialization. Web routes expose liveness/capabilities only.

## What does not work yet

No durable case/revision storage, verification command, authenticated operator workflow, cross-request stale-revision enforcement or restart-surviving audit trail exists. `storage.py` and `verification.py` reserve boundaries; they do not implement those capabilities. No application path records an independent callback or creates an authoritative `VERIFIED` status.

Arbitrary text extraction needs a compatible configured provider/model. Live accuracy is unmeasured; the recorded extraction run is disabled and failed. Fixture mode recognizes exact bundled synthetic sources and does not support arbitrary email/invoice pairs. PDF/OCR, separate routing and other payment schemes/countries remain unsupported. The application does not execute or approve payments.

## Final requirement checklist

| Requirement | Evidence / status |
| --- | --- |
| 1. Clean installation | **BLOCKED / unverified.** `make verify VENV=/tmp/payproof-phase1-freeze-xyca0xh0` created a fresh venv, then pip failed package-index DNS. Automatic review could not authorize the network retry because its review model was at capacity; retry was not executed. Only 8/28 pinned development packages were available in the read-only local wheel cache. Existing dependencies were not copied into the fresh venv and were not counted as a clean install. |
| 2. Starts locally | CLI `check`, seeded demo and fixture file analysis pass. Flask initializes and both in-process GET routes return 200. **HTTP binding unverified here:** sandbox denies socket creation (`PermissionError`); no server was left running. |
| 3. Environment documented | [README configuration](../README.md#how-to-run); process environment only, no automatic `.env` loading. |
| 4. Tests pass | `make verify`: all 588 tests pass (including all 73 red-team checks); Ruff lint/format and strict mypy pass. |
| 5. One-command benchmark | `make benchmark`; also included in `make verify`. |
| 6. Saved results | [Gold report](../benchmarks/phase1-v1/results/gold/report.json) and [summary](../benchmarks/phase1-v1/results/gold/summary.txt). Existing configured-extraction failure artifacts retained. |
| 7. Seeded demo | Actual CLI invocation with scripted synthetic `REVIEWED` input produces `VERIFY / DESTINATION_CHANGED`, full old/new evidence and trusted callback. Scripted QA review is not independent human verification. Wheel smoke also runs the explicitly simulated demo. |
| 8. Evidence visible | CLI displays baseline provenance, current exact source/excerpts, field differences, state/reasons and trusted callback. |
| 9. Changed details => VERIFY | Complete reviewed supported GB/DE changes only; all 10 supported diagnostic changes detected. Unsupported changes must remain `UNCERTAIN`. |
| 10. Insufficient evidence => UNCERTAIN | Missing/failed/unsupported/conflicting/unreviewed cases covered by tests and gold benchmark. |
| 11. Human-only VERIFIED later | Comparison/model states exclude `VERIFIED`; no verification command exists. Future explicit human attestation must be separately source/revision-bound. Schema validation alone does not authenticate a person. |
| 12. No committed secrets | Current tracked example secret fields are empty; `.env` and private-key files are ignored. **Historical gate unresolved:** prior credential-like value remains in Git history; no owner revocation/rotation is confirmed. No credential was used during freeze. |
| 13. Architecture matches | Core contracts, pure comparator, review and provenance match the architecture. Persistent/gated web workflow, independent verification, lifecycle tests and release-corpus gates remain unimplemented; full conformance cannot be claimed. |
| 14. Limitations documented | This handoff, README and retained red-team residual-risk reproduction. |

## Current benchmark numbers

Dataset: `payproof-phase1-diagnostic-30-v1`; rule: `iban-gb-de-v1`.
Corpus SHA-256: `3bc6dcafaeb661b00cf22fd06fc86802c8db642c41d9228676faae3b546a0c7f`.

| Gold metric | Measured result |
| --- | --- |
| Total cases | 30 |
| Correct states / exact result agreement | 30/30 / 30/30 |
| Consequential changes | 13 |
| Correct VERIFY detections | 10 |
| Changes missed as VERIFY | 3, all unsupported abstentions (PP-07, PP-08, PP-29) |
| Supported changes detected | 10/10 |
| Critical false UNCHANGED | 0 |
| Unchanged incorrectly VERIFY | 0 |
| Uncertainty handled correctly | 13/13 |
| Deterministic-comparison failures | 0 |
| Unreviewed gold gate agreement | 30/30 |

Gold source review is simulated, not an independent callback. Scoring digest: `b2b2e52c28855690e2a8a51f0fa8be847635cc2986adb82c825849d818cda67c`. The closing run preserves the corpus and expected outcomes.

The retained configured-extraction run records 30 `NOT_CONFIGURED` failures, 0/30 successful classifications, zero detections and zero comparison failures. Its pipeline/review tracks share the same attempts. No live rerun or fixture substitution was performed during closing. Independent label review is `PENDING`; the 30 public cases do not fulfill the architecture's 36-case/12-held-out release corpus. Actual human-action enforcement and independent verification remain `NOT_EVALUATED`.

## Commands and validation

Requires Python 3.11+, venv, pip, GNU Make and package-index access for initial setup. Run from the repository root:

```bash
make verify                 # setup, lint, typecheck, tests, check, benchmark, build
make demo                   # read all evidence, then type REVIEWED
make demo-smoke             # explicitly simulated source review, synthetic demo only
make benchmark              # writes gold JSON + human-readable summary
make serve                  # read-only loopback server; Ctrl-C to stop
```

Individual gates: `make lint`, `make typecheck`, `make test`, `make build`. `make benchmark-extraction` and replay of the recorded failed extraction report return nonzero with disabled extraction; this is expected failure reporting, not a passing live evaluation.

CLI exit 0 means supported comparison complete (`UNCHANGED` or `VERIFY`); exit 2 means uncertainty/CLI usage error; exit 1 means operation failure. None grants permission to pay. `demo --no-review` intentionally returns 2.

Closing validation on 2026-10-05:

- `make verify` in the existing `.venv`: exit 0. Ruff checks pass (44 files formatted); strict mypy passes (24 source files); **588 tests pass**. Initialization validates four trusted vendors and ten requests without creating a database or calling a provider.
- The gold benchmark passes both tracks and saves the JSON/summary above; all counts and the scoring digest remain unchanged.
- Production wheel/source build and isolated wheel fixture/demo smoke pass. Package validation imports directly from the wheel using the existing environment's dependencies; it is not a fresh dependency install or a deployed persistent service.
- The actual seeded CLI with scripted synthetic review produces `VERIFY`, displays both full identities/provenance/exact quote/callback and contains no authoritative `VERIFIED`. Exact-match fixture file analysis produces `UNCHANGED / DESTINATION_MATCH` (exit 0).
- The missing-account vendor-notice fixture, through the existing core workflow with its original source kind, produces `UNCERTAIN / DESTINATION_MISSING`. The file CLI has no vendor-notice flag, so this was not misrepresented as file analysis. Unreviewed seeded CLI produces `UNCERTAIN / REVIEW_REQUIRED` (exit 2).
- Flask initializes and returns 200 for `/healthz` and `/` in-process, with `writable=false`. Actual loopback socket creation is sandbox-blocked, so HTTP listener startup is unverified.
- Current tracked files and this handoff contain none of the historical credential value; example secret fields remain blank. Historical revocation and a complete clean-install run remain outstanding.

No new blocking failure was reproduced in the implemented deterministic core. No provider call, authentication feature, integration, database, verification event or secret-management action was added. The incomplete release gates above prevent an unconditional Phase-1-ready declaration.

## Exact demo fixture

| Item | Exact value / reference |
| --- | --- |
| Vendor | `Synthetic PayProof Demo Supplies` |
| Trusted record | [demo-account-3821.json](../payproof/fixtures/trusted_vendors/demo-account-3821.json) |
| Vendor ID | `9fd65164-9dfe-5226-a462-2ef5d7afc6f5` |
| Baseline revision | `5f64bba7-2a0f-5297-8514-96d113a4ab27` |
| Trusted account | `GB46TEST00000000003821` |
| Trusted source | `synthetic-onboarding/demo-account-3821`, verified `2026-10-03T08:00:00Z` in the synthetic record |
| Current request | [demo-account-change.json](../payproof/fixtures/requests/demo-account-change.json), fixture ID `demo-account-change` |
| Requested account | `GB57TEST00000000009928` |
| Exact evidence | `Please pay this invoice to IBAN GB57TEST00000000009928.` |
| Stored span | Character offsets `[273, 328)`, email source digest `dab276aa4bb8b5528e1a6bda7a9fa53159c3a3f5414767b2fdb67bf1c9a4aec8` |
| Trusted callback | Fictional phone `+1-202-555-0182`, from prior onboarding; never selected from current request/reply-to |
| After explicit source review | `VERIFY / DESTINATION_CHANGED`; independent checking required |
| Without source review | `UNCERTAIN / REVIEW_REQUIRED` |

Exact captured text (the fixture includes a final newline):

```text
From: accounts@payproof-demo.example
Reply-To: accounts@payproof-demo.example
Vendor: Synthetic PayProof Demo Supplies
Invoice: DEMO-001
Amount: 1250.00 GBP
Bank: Synthetic Demo Bank
Payment details have changed.
Reason: We moved our payment instructions to a new account.
Please pay this invoice to IBAN GB57TEST00000000009928.
```

The runtime demo captures fresh IDs/timestamps and rebinds the same exact evidence. Full accounts determine comparison; endings 3821/9928 are display aids. All accounts/contacts are fictional. Source review creates no human verification event.

## Decisions that must not be casually changed

- AI supplies observations only; no fraud/safety/verification verdicts, tools, baseline selection or trust creation.
- Preserve full immutable source evidence and exact spans; no invented values, silent truncation, parser key overwrites or checksum/Unicode repairs.
- Preserve manual vendor/baseline selection and the previously trusted independent contact. A current request cannot establish its own trust or callback.
- Keep the comparator pure and deterministic, full-identity based and fail closed. Retain support bounds, all ambiguity blockers, source-review requirement and machine-readable reasons.
- Keep source review separate from independent verification. Later `VERIFIED` is a scoped human event that never rewrites the original comparison or updates a baseline automatically.
- Preserve one Python application, pinned minimal dependencies and the planned standard-library SQLite boundary. Do not add distributed infrastructure for this workload.
- Preserve frozen evaluation labels, stage-separated metrics and original failed observations. Unsupported abstention and disabled extraction are not successful change detections.

## Known bugs and highest-priority Phase-2 work

1. **Live-reliability blocker: wrong-role omission.** An extractor can quote a historical/trusted account while omitting a current differing account. Before review the state is uncertain; false source-review acknowledgement can yield `UNCHANGED`. The executable reproduction is `test_wrong_role_and_omitted_current_instruction_remain_a_human_review_limit` in [test_redteam.py](../tests/test_redteam.py). Exact quotes/checksums cannot prove completeness. Keep live extraction unendorsed until independently evaluated; retain the full-source review gate and measure omissions/wrong-role selections. No heuristic role parser was added just to hide the reproduction.
2. Resolve clean-install evidence on a host with package-index access and confirm owner revocation of any live historical credential. Do not declare either completed from this checkout.
3. Before any writable/operational workflow, implement the already planned persistent snapshots/revisions and separate explicit human verification boundary. Enforce trusted-contact/current-revision checks atomically and add restart, failed-write, duplicate and stale-submission lifecycle tests. Authenticate future human actions before accepting attestations. These are unfinished architecture obligations, not polishing work.
4. Obtain independent label review and the frozen 36-case/12-held-out release evaluation; separately evaluate actual live extraction on synthetic data without gold correction or inflated aggregate scores.

No additional deterministic comparison, schema, provenance or initialization defect was identified by this closing pass. Conservative lexical rejection of adjacent numeric columns/footnotes and incomplete provider wall-clock deadlines remain documented limitations. Authentication, integrations and visual features were not added during freeze.
