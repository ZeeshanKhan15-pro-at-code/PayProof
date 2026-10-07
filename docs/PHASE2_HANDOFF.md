# Phase-2 release-candidate handoff

Assessment: 2026-10-07. **PARTIAL verification; complete-release freeze withheld.** The mechanism and persistent operator workflow work in synthetic tests. The strict gold gate fails, live extraction is unmeasured, clean install and actual HTTP are infrastructure-blocked, and historical credential revocation is unconfirmed. No new product features or safety/label changes were made for this assessment.

## What works

- One gated Flask workflow over the same contracts/SQLite commands as the private CLI: prior vendor entry/selection, bounded UTF-8 sources, extraction, exact evidence display, explicit source review, deterministic comparison, independent human check and retained history.
- Strict Pydantic/schema/source/hash/full-token validation. Missing stays missing; failures cannot produce decisive comparisons or human confirmation. Live mode has no fixture fallback and sends no baseline/contact to the model.
- Full GB/DE IBAN normalization, leading zeros preserved, no Unicode/punctuation/OCR repair or account-tail equality. Only `UNCHANGED`, `VERIFY`, `UNCERTAIN` comparison states.
- Independent bounded source inventory catches tested competing/omitted/historical destination regions and exposes exact context. Confidence/blanket review cannot suppress a competing account.
- SQLite migration v1, immutable snapshots/events, restart persistence, atomic expected-revision writes, idempotent human actions, rollback and current baseline/contact/engine bindings.
- Separate human outcomes and scoped confirmation, derived `VERIFIED` only from explicit positive current human action. Trusted callback is taken only from the frozen baseline; comparison is preserved. `UNCERTAIN`, failed extraction, missing review and stale revisions cannot confirm.
- Signed gated sessions, logout/restart revocation, CSRF/origin/form checks, escaped evidence/CSP/no-store, input/rate limits and configured-literal secret guards.
- Wheel/sdist build, actual temporary-target wheel installation and outside-checkout migration/workflow/assets smoke using existing pinned dependencies. Production WSGI health passes independently of actual listener availability.

## Verification boundaries and current benchmark

The final [release report](PHASE2_RELEASE_REPORT.md) and [saved audit directory](../benchmarks/phase2-freeze/) record commands/statuses. The full synthetic suite is 754 passing tests; lint/format, strict mypy and package checks pass in the existing interpreter. Its 28 dependency versions match pins, but it is not a clean installation.

Reviewed held-out **gold**: 72 cases; **FAIL**, 56/72 states, 53/72 exact results, 12/24 source-correct changed-destination `VERIFY` detections, 12 changed-case abstentions, zero critical false `UNCHANGED`, zero false `VERIFY`, 30/33 strict correct uncertainty, 33/33 uncertain-state recall, 19 comparison scoring failures and zero failed operations. Extraction metrics are NOT_RUN. Independent label review remains PENDING. The unreviewed gold gate's 72/72 states with 53/72 exact matches is a separate failing diagnostic, not end-to-end performance.

**Live extraction / live end-to-end: NOT_MEASURED, BLOCKED / NOT_CONFIGURED.** No provider calls completed. Do not substitute gold, fixture or mocked results. Raw final gold [report](../benchmarks/phase2-freeze/gold/report.json) and [summary](../benchmarks/phase2-freeze/gold/summary.txt) retain the unchanged labels and all failing IDs. Historical results are preserved, never silently overwritten.

## What does not work or remains unproven

- Fresh pinned install: new venv succeeded; install blocked by package-index DNS/network. Verbose value-free diagnosis confirms DNS failure; a “no matching distribution” summary does not prove a bad pin.
- Actual production HTTP: installed Gunicorn/socket gate blocked by EPERM at socket creation. WSGI/test-client success does not prove a listener.
- Real live provider/model compatibility, extraction accuracy and end-to-end recall: environment lacks key/model/live mode.
- Historical credential-like literal: owner has not confirmed synthetic status/revocation. Treat it as exposed until confirmed; revoke/rotate if genuine. Never reuse or retrieve it for a provider test.
- Strict gold gate: 16 conservative state/reason mismatches and three reason-only mismatches remain. Independent review of instruction roles and evaluation expectations is needed. Do not weaken the competing-account gate or change v1 labels to obtain a pass.
- Later migrations/backup-restore/retention procedures, public deployment and individual operator identity are not established.

## Known defects and residual risks

No known unfixed reproduced P0 outcome or P1 workflow-integrity defect remains in the implementation. Historical credential exposure is an open **P1 release risk pending owner triage**, not a confirmed active-key assertion. Full red-team coverage and limitations are in [PHASE2_REDTEAM_REPORT.md](PHASE2_REDTEAM_REPORT.md).

P2: lexical discovery is not exhaustive; extraction can omit unrecognized instructions/roles. Provider timeout is per socket I/O, not a hard wall-clock limit. Case creation is not idempotent and may repeat extraction cost. Rate/session storage is process-local. Stronger validation can refuse old unsafe snapshots; preserve originals and recover/create a new case privately, never silently relabel history. Host/DB administrators can alter data; audit records are not cryptographically tamperproof. Unknown/transformed/historical secrets are not comprehensively detected. Contacts are prior human trust assertions; human actions do not prove a call or ownership.

## Commands

Run from repository root with the pinned environment. Use new result/data directories:

```bash
make setup
make lint typecheck test
.venv/bin/python -m payproof check
PAYPROOF_DATA_DIR=/tmp/payproof-private-new .venv/bin/python -m payproof workflow init
make build
.venv/bin/python scripts/check_wheel.py --http
.venv/bin/python scripts/check_credential_history.py
.venv/bin/python -m payproof.heldout_benchmark
.venv/bin/python -m payproof.heldout_benchmark --evaluate-gold --output /tmp/payproof-gold-new
.venv/bin/python scripts/smoke_live_extraction.py
.venv/bin/python -m payproof.heldout_benchmark --live --output /tmp/payproof-live-new
```

Gold currently exits 1; HTTP/history/missing-live checks may exit 2. They are not passing gates. The older `make verify` stops at its failing 30-case diagnostic and does not reach build; use explicit stages so one failed evaluation does not prevent recording other gates.

## Exact demo and configuration

Primary definition: [fixtures/demo_proof/acme.json](../payproof/fixtures/demo_proof/acme.json). Vendor **Acme Supplies (synthetic)**; trusted full `GB46TEST00000000003821`; new full `GB57TEST00000000009928`; result `VERIFY / DESTINATION_CHANGED`; fictional prior callback `+1-202-555-0182`; provenance `synthetic-onboarding/acme-proof-3821`. Four controls cover unchanged, conflict, disabled extraction and historical-current competition/omission. [DEMO_SCRIPT.md](DEMO_SCRIPT.md) supplies the walkthrough.

```bash
.venv/bin/python -m payproof.demo_proof --output /tmp/payproof-proof-new --seed-data-dir data/acme-new
export PAYPROOF_DATA_DIR="$PWD/data/acme-new"
make serve
```

Seeding creates no review/comparison/confirmation. Static report review is explicitly simulated. Sources, accounts and callback are fictional; do not call the callback. A separate synthetic role-play human action remains labeled as simulation and preserves the comparison.

Environment only; `.env` is not auto-loaded. Default extraction disabled; fixed OpenAI Responses endpoint needs an explicit compatible model plus fresh credential for live. Operator pages need separate random `PAYPROOF_SECRET_KEY`/`PAYPROOF_OPERATOR_TOKEN` (32+ chars); production additionally needs restricted HTTPS and one worker. `PAYPROOF_DATA_DIR` must be private persistent local storage, not shared network disk. Unknown settings fail closed. See README's full variable table.

## Decisions to preserve and Phase 3 priorities

Keep exact evidence/source binding, strict schemas, conservative full-identity normalization, deterministic states, unknown/competing-evidence abstention, source-only model input, prior trusted callback, separate explicit human action and atomic revision checks. No automatic trust/baseline update, verdict, payment or fallback. Keep the frozen benchmark protocol and raw failures; independently review disputed labels and version any future corpus before predictions.

First close clean install, real HTTP, credential triage and configured live evaluation gates. Independently assess the 19 gold mismatches without suppressing safety uncertainty. Then improve narrowly scoped instruction-resolution/evaluation coverage, bounded provider execution, case-create retry handling, backup/retention practice and functional presentation. Individual identity/deployment hardening require justified scope; no banking, payments, generic fraud classifier or broad integration work.

## Commit/tag decision

The requested `milestone: phase 2 hardened PayProof complete` commit and `phase2-freeze` tag are **withheld**: a complete release is not acceptable while the evaluation gate fails and required operational/security evidence remains blocked. The repository changes and retained evidence are reviewable; no credential history rewrite or secret revocation is performed by this task.
