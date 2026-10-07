# PayProof integrator context

As of 2026-10-07: persistent Phase-2 mechanism implemented, release verification **PARTIAL**; complete milestone/tag withheld. Read [PHASE2_RELEASE_REPORT.md](PHASE2_RELEASE_REPORT.md) for final statuses, [PHASE2_HANDOFF.md](PHASE2_HANDOFF.md) for commands/limits. No production-readiness claim.

## Product boundary

Exactly one problem: requested payment destination may differ from prior trusted vendor data. Surface supported changes and require independent human checking. No generic phishing/fraud classification, autonomous approval, bank ownership assertion, payment processing, banking/accounting integrations or AgentGate.

## Architecture and directory map

One Python/Pydantic/Flask package, server-rendered forms, stdlib SQLite/HTTP, Gunicorn one worker/two threads. Pinned 28-package dev dependency set, no ORM/queues/frontend services.

| Path | Responsibility |
| --- | --- |
| `payproof/schemas.py`, `validation.py` | Strict canonical v1 contracts, duplicate/nonfinite JSON rejection, cross-record grounding/state validation |
| `workflow_contracts.py`, `verification.py` | Narrow human action/events, CaseInputs, StoredCase freshness/status |
| `documents.py`, `provenance.py` | Bounded immutable text capture, digest/exact quote/full token checks |
| `extraction.py`, `extraction_contract.py`, `openai_extraction.py` | Mode selection, strict provider wire observations, source grounding and safe failures |
| `instruction_safety.py` | Independent bounded source inventory and competing/omitted/reference-region gate |
| `normalization.py`, `comparison.py` | Conservative full identity and pure deterministic comparison |
| `cases.py`, `storage.py`, `migrations/001_initial.sql` | Orchestration, SQLite immutable snapshots/events and atomic revision commands |
| `web.py`, `operator_web.py`, `templates/`, `static/` | Gated minimal forms, escaped evidence, CSRF/origin/input/state protections |
| `cli.py`, `workflow_cli.py`, `presentation.py` | Private CLI, explicit review/human actions, escaped evidence/result display |
| `benchmark_harness.py`, `benchmark_scoring.py`, `heldout_benchmark.py`, `evaluation_contracts.py` | Separate gold/review/extraction/conditional-pipeline evaluation |
| `demo_proof.py`, `fixtures/demo_proof/acme.json` | Curated five-case mechanism proof and saved-artifact report, not live performance |
| `tests/`, `scripts/`, `benchmarks/`, `docs/` | Synthetic regressions, build/live/history tools, immutable results/protocol and handoffs |

## Contracts and invariants

Pydantic strict/frozen/extra-forbid. Boundary JSON uses `parse_contract`; Python input needs typed UUID/UTC datetime/tuples. `TrustedVendorRecord`, `PaymentRequestEvidence`, `EvidenceSpan`, `NormalizedPaymentIdentity`, `ComparisonResult`, `HumanVerificationRecord`, `SourceDocument`, `SourceReview`, `CaseContract`; workflow `CaseInputs`, `IndependentCheckAction/Event`, `StoredCase`. See [DATA_MODEL.md](DATA_MODEL.md).

- Comparison states only **UNCHANGED / VERIFY / UNCERTAIN**. Equality is not permission to pay. No model verdict/state fields.
- `VERIFIED` is separate derived current human confirmation, never comparison output. Human event needs explicit true, exact check, prior trusted callback/source, outcome, server timestamp; positive outcome also person/role. Negative/inconclusive never confirms. Comparison remains preserved.
- Missing/failed/unreviewed/ambiguous/unsupported evidence cannot be decisive. Known competing destinations remain UNCERTAIN even with high model confidence or broad human source acknowledgement.
- Full GB/DE checksum-valid IBANs, ASCII spaces/case only. Preserve zeros; no tails, Unicode/punctuation/OCR repair, fuzzy matching or bank-display-name equality decision.
- Every consequential extracted candidate is tied to a frozen source hash/ID/exact excerpt/offset. Binding is not source authenticity, completeness or intent proof.
- Baseline/contact must predate request. Request cannot establish trust or replace callback. No automatic baseline update, human event or payment action.

## Persistence/security

SQLite v1: contacts/vendor revisions/heads, sources, extraction attempts, case revisions/heads, workflow events, verification attempts and human confirmations. WAL, FK, synchronous FULL; new private directory 0700, DB0600. Initialization/restart checked; unknown/incomplete/unversioned nonempty schema rejects. Immutable IDs cannot be reused with different facts. BEGIN IMMEDIATE, expected case/vendor revisions, transaction rollback, idempotent human action UUID and unique confirmation per comparison.

Staleness includes source/case/vendor/contact and engine fingerprint (`comparison.py`, `normalization.py`, `schemas.py`, `instruction_safety.py`). Refresh clears current review/comparison/attestation; old events remain historical. Extraction runs outside transaction; baseline revision rechecked before commit. Host/DB admins trusted; no crypto tamperproof guarantee. Raw provider bytes are transient, not durable operator audit.

Operator gate: shared passphrase + signing secret, labels attribution only. HttpOnly/SameSite Strict/Secure production cookie, CSRF + same-origin + strict form fields, escaped source HTML, CSP, no-store, limits. Process-local registry revokes logout/restart; one worker required. Health is public liveness, no DB/provider initialization. Literal configured secrets reject before upload/storage/display; unknown/encoded/historical secrets not universally detected.

## Provider/configuration

Environment authoritative; `.env` never auto-loaded. `PAYPROOF_ENV`, `PORT`, `DATA_DIR`, `EXTRACTION_MODE`, `PROVIDER_API_KEY`, `PROVIDER_MODEL`, `EXTRACTION_TIMEOUT_SECONDS`, `SECRET_KEY`, `OPERATOR_TOKEN` under `PAYPROOF_` prefix. Defaults development/8000/data/disabled/30; credentials/model absent. Unknown/malformed config rejects. Separate random 32+ signing/operator secrets for writable pages; production HTTPS and private persistent volume. Do not copy/reuse historical credentials.

Fixed `https://api.openai.com/v1/responses`, stdlib HTTPS, strict JSON schema, source-only IDs/kind/text, no trusted record/contact/tools, store=false, one attempt/no fallback/retry/stream/background/redirect. Limits 16 docs/20k characters, 262144 provider bytes, 8000 output tokens, 64 total candidates. Exact unique quotes/string literal/full account tokens mandatory. Unsupported source values stay verbatim but cannot match a supported identity. `NOT_CONFIGURED`, `TIMEOUT`, `PROVIDER_UNAVAILABLE`, `INVALID_RESPONSE`, `EVIDENCE_INVALID` become explicit unreadable safe attempts; invalid input/config rejects before provider. Socket timeout is not a total execution deadline. Real live key/model/network not configured here.

## Results and red team

Final suite **754 passed**; Ruff lint/format, strict mypy, wheel/sdist and outside-checkout installed target/migration/restart/operator/assets/health checks pass using existing pinned dependencies. Fresh setup blocked by index DNS/network; actual Gunicorn listener blocked by socket EPERM. Historical `.env.example` literal needs owner confirmation/revocation; scanner also flags an intentional synthetic private-key test header, not real private key material. No values/logs retained.

Saved `benchmarks/phase2-freeze/gold/`: 72-case gold **FAIL**, 56/72 states, 53/72 exact, 12/24 changes detected, 12 changed cases abstained, critical false UNCHANGED0, false VERIFY0, strict uncertainty30/33 (state-only33/33), 19 comparison scoring failures, failed operations0. Gold extraction metrics NOT_RUN. Unreviewed gate72/72 states,53/72 exact remainsFAIL. **Live and live end-to-end NOT_MEASURED / NOT_CONFIGURED**, zero calls; independent label reviewPENDING. Gold/live/test/demo metrics must never be pooled. Corpus SHA256 `203a43619b2baaf516063e5f2add4ce86a828c8ac8dc6c1e29edb6e09363c2d0`. Keep v1 sources/labels/protocol immutable; independent review/version new labels before predictions. Do not optimize against held-out v1.

Fixed red-team P0: historical-only extraction plus omitted split/Unicode/malformed current account returned UNCHANGED; independent discovery now catches tested regions and abstains. Fixed P1: copied-session logout/rotation replay and configured-secret boundary/reflection/retention gaps. Tests cover direct HTTP bypass, conflicting/duplicate fields, stale writes, concurrent confirmation, invalid IDs/transitions, provider/schema/timeouts, oversized/encoding failures and inert HTML. See [PHASE2_REDTEAM_REPORT.md](PHASE2_REDTEAM_REPORT.md); passing synthetic probes is not certification.

Remaining: source-role/discovery incompleteness; gold utility/reason mismatches; hard execution deadline; case-create duplicate/cost behavior; historical credential triage; later migrations/backup/retention, stronger identity/public hosting. Old unsafe snapshots can reject on read; preserve/recover privately rather than relabel.

## Commands and demo

`make setup`; `make lint typecheck test`; `.venv/bin/python -m payproof check`; `make build`; `scripts/check_wheel.py --http`; `scripts/check_credential_history.py` via `.venv/bin/python`. Older `make verify` stops at failing diagnostic benchmark; run all stages explicitly. Initialize private SQLite with `PAYPROOF_DATA_DIR=/tmp/payproof-private-new .venv/bin/python -m payproof workflow init`. `make serve` / `make production` for configured gated UI. Live `scripts/smoke_live_extraction.py`; held-out `python -m payproof.heldout_benchmark` validation, `--evaluate-gold` or `--live` with NEW `--output` directory. Failures/blocks remain nonzero.

Acme demo: `GB46TEST00000000003821` → `GB57TEST00000000009928`, VERIFY/DESTINATION_CHANGED, fictional prior callback `+1-202-555-0182`, provenance `synthetic-onboarding/acme-proof-3821`. `python -m payproof.demo_proof --output /tmp/payproof-proof-new --seed-data-dir data/acme-new`; point `PAYPROOF_DATA_DIR` there, configure gate privately, open `/operator`. Cases initially unreviewed/uncompared/unconfirmed; report review explicitly simulated. Five cases include unchanged, conflict, disabled failure and old-only omission. No actual callback; separate labeled human role-play only. See [DEMO_SCRIPT.md](DEMO_SCRIPT.md).

## Do not rewrite / next work

Preserve product boundary, strict contracts/grounding, state authority, full-identity conservative normalization, competing-evidence abstention, source-only provider, baseline-sourced callback, explicit revision-bound human events, transactions and frozen labels/failures. No broad feature rewrite or schema relaxation to make a model/benchmark pass.

Phase 3: first close deployment/install/credential/live gates and independently review gold mismatches; then bounded provider execution, scoped instruction resolution with provenance, retry/retention practice and functional presentation polish. Only justify further input schemes, identity or integrations with real evaluation needs. Complete milestone/tag remains withheld until failed/blocked release gates are resolved.
