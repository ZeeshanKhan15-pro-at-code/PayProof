# PayProof

PayProof compares requested payment destinations with previously trusted vendor information and requires independent human checking when they differ. The current implementation includes a no-login isolated temporary public workspace and a persistent private operator workflow. Current assessment: **PARTIAL**. The no-login workflow, tests and synthetic installed-package HTTP startup pass. Gold evaluation still fails, successful live extraction remains unverified after Featherless HTTP403, and clean-install/credential-revocation closure remains pending. The earlier phase reports are historical evidence. See the [release report](docs/PHASE2_RELEASE_REPORT.md), [handoff](docs/PHASE2_HANDOFF.md) and [integrator context](docs/AI_HANDOFF.md). No production-readiness or security certification is claimed.

### Problem

A plausible invoice can request a destination different from the vendor's prior instructions. PayProof shows the old/new destination, exact evidence and known-good callback. It does not classify fraud, approve payments, process money or establish bank account ownership.

### Implemented architecture

One Python package: Flask server-rendered forms, strict Pydantic contracts, stdlib SQLite, synchronous OpenAI Responses / Featherless chat-completions adapters and a pure deterministic comparator. Dependencies are pinned in `requirements-dev.txt`; no ORM, queue, frontend framework or distributed service.

```text
trusted vendor + prior callback -> immutable SQLite baseline revision --+
                                                                      |
pasted/uploaded UTF-8 text -> source-only extraction                    |
                           -> strict schema + exact evidence validation|
                           -> source inventory + explicit human review|
                           -> deterministic normalization/comparison <-+
                           -> UNCHANGED / VERIFY / UNCERTAIN
                           -> source/evidence/result history in SQLite

explicit independent human check using prior trusted callback
                           -> separate revision-bound attestation/event
                           -> VERIFIED derived only if confirmed/current
                           -> no payment action; comparison is preserved
```

The private `workflow` CLI and gated `/operator` forms share backend contracts and storage commands. Operators create/select prior trusted records, paste/upload synthetic UTF-8 `.txt`/`.eml` documents, run extraction, inspect sources/spans, acknowledge source review, compare and optionally record an independent human outcome. SQLite retains immutable snapshots/events and timestamps. Migration2 adds reviewed baseline drafts/assertions and idempotent submissions, preserving migration1 data on restart. Web forms support explicit baseline revision and current-source replacement; old results become stale/historical. Independent human receipts are JSON attestations, not ownership certificates. No deletion interface or automatic trust/baseline replacement exists.

### AI role

Modes are explicit: `disabled`, `fixture`, `live`. Live sends only source IDs, kinds and text to the configured provider: OpenAI Responses requests strict JSON schema and `store=false`; Featherless chat completions requests JSON-object mode with the schema in the prompt. Both require the same strict local schema/grounding and do not execute tools. The model never receives/selects the baseline or callback, returns verdicts or records verification. Unknown fields, malformed JSON/schema, fabricated/nonunique excerpts and clipped account evidence fail closed. Missing stays missing. Timeouts/provider failures are explicit unsuccessful attempts; live never falls back to fixtures. Provider/model compatibility and live accuracy are **unmeasured**. See [LIVE_EXTRACTION.md](docs/LIVE_EXTRACTION.md).

### Deterministic safety layer

Full checksum-valid GB/DE IBANs only. Normalize ASCII spaces and letter case; preserve zeros/full identity. Do not repair Unicode, punctuation, OCR, masked values or unsupported schemes. Bank names, sender, amount, currency and invoice context do not determine destination equality.

| Comparison | Meaning |
| --- | --- |
| `UNCHANGED` | Complete supported reviewed destination matches the prior baseline; destination equality only |
| `VERIFY` | Complete supported destination differs; independently check the exact instructions |
| `UNCERTAIN` | Failed, missing, unsupported, conflicting, incomplete or unreviewed evidence prevents reliable comparison |

An independent bounded lexical inventory exposes competing/omitted source regions. Model confidence and broad source acknowledgement cannot suppress them; context hints do not prove intent. Known competing instructions abstain toward `UNCERTAIN`.

`VERIFIED` is never an AI/comparison state. Only an explicit human action recording the exact check, previously trusted contact, outcome, person/role, server time and optional notes can create a scoped confirmation. The comparison is preserved. Stale case/vendor/contact/engine revisions require fresh review/comparison. Negative/inconclusive outcomes do not confirm. Human action IDs are idempotent; case creation is not. See [DATA_MODEL.md](docs/DATA_MODEL.md).

### Current benchmark

The final [72-case gold run](benchmarks/phase2-freeze/gold/report.json) and [summary](benchmarks/phase2-freeze/gold/summary.txt) use supplied gold observations and simulated source review. They are **not live extraction or human-review performance**. Independent label review is pending; frozen labels/protocol were not changed.

| Reviewed gold metric | Saved result |
| --- | --- |
| Overall status | **FAIL**, exit 1 |
| Correct states | 56/72 |
| Exact state/reasons/values/evidence | 53/72 |
| Known consequential changes | 24 |
| Correct `VERIFY` detections | 12/24 |
| Changed cases abstained `UNCERTAIN` | 12 |
| Critical false `UNCHANGED` | 0 |
| False `VERIFY` on unchanged cases | 0 |
| Correct uncertainty including reasons | 30/33 |
| Uncertain-state recall alone | 33/33 |
| Comparison scoring failures / failed operations | 19 / 0 |
| Extraction metrics | NOT_RUN |

The failures remain visible: 16 conservative state/reason mismatches and three reason-only mismatches. Abstention is not successful change detection. The separate unreviewed gate has 72/72 state matches but 53/72 exact matches and remains FAIL. Live extraction and live end-to-end metrics are **NOT_MEASURED / NOT_CONFIGURED**. Historical Phase-1 30/30 is not current performance; its later guard run is 28/30. Gold/live/curated demos are never pooled.

### Seeded evidence proof

[DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) gives a 2–4 minute walkthrough: Acme 3821→9928 change, supported unchanged, conflicts, disabled-extraction failure and historical-only extraction omission. The proof runner uses authored synthetic observations and explicitly simulated report-only review; it never creates human confirmation. Optional operator seed cases start unreviewed/uncompared.

```bash
.venv/bin/python -m payproof.demo_proof \
  --output /tmp/payproof-proof-new-run \
  --seed-data-dir data/acme-demo-new-run
```

Use new directories. The [saved report](benchmarks/demo-proof-v1/report.html) retains all inputs/outcomes and separate benchmark artifacts. Demo success is mechanism proof, not held-out model accuracy. Full accounts are compared; suffixes are display aids. Contacts/accounts are fictional; do not call the synthetic callback.

### Current limitations

- Synthetic evaluation; independent label review pending; failed strict gold gate; no live accuracy. Discovery cannot prove exhaustive coverage/intent, and unrecognized OCR/role/omission errors remain possible.
- One shared operator passphrase and attribution labels, process-local session registry. Logout/restart revoke sessions. One Gunicorn worker required; no multi-user identity/tenant isolation.
- UTF-8 text, 16 sources/20,000 aggregate characters, 100,000-byte HTTP body. No PDF/OCR, integrations, other schemes or automatic vendor matching.
- Socket I/O timeout is not a complete provider wall-clock deadline. No automatic retries. Duplicate case creation can incur repeated extraction costs, bounded by burst limits.
- Host/database administrators are trusted; application history is not cryptographically tamperproof. Private SQLite/WAL/backups need access controls. Stronger validators can reject old unsafe snapshots; never silently relabel them.
- Current credential fields are blank; historical credential-like material needs owner revocation/synthetic-status confirmation. Pattern scans cannot prove absence/revocation. Guards do not detect every encoded/unknown secret.
- Fresh pinned install is blocked here by package-index DNS/network access. Installed-wheel checks use the existing pinned interpreter. Real production socket startup is blocked by sandbox EPERM; passing in-process health/request tests are separate evidence.

See [PHASE2_REDTEAM_REPORT.md](docs/PHASE2_REDTEAM_REPORT.md) for fixed P0/P1 findings and residual risks. Phase 3 starts with operational gates and independent evaluation, then presentation polish without weakening safety.

### How to run

Python 3.11+, `venv`, pip, GNU Make; first setup needs package-index access:

```bash
make setup
make lint typecheck test
make build
.venv/bin/python -m payproof check
```

`make verify` is the older aggregate: its diagnostic benchmark exits 1 and stops before build. Run the explicit commands above and benchmark separately to exercise every gate; never count that failure as a pass.

| Command | Actual behavior |
| --- | --- |
| `make setup` | Complete pinned set and editable installation |
| `make lint typecheck test` | Lint/format, strict mypy, complete synthetic suite |
| `make build` | Wheel/sdist plus installed-target smoke using existing dependencies |
| `.venv/bin/python scripts/check_wheel.py --http` | Installed Gunicorn listener/health; exit 2 for infrastructure block |
| `.venv/bin/python -m payproof workflow init` | Private SQLite v1 initialization |
| `make serve` | Loopback Flask; browser landing and `/workspace` require no login; private `/operator` retains its gate |
| `make production` | One Gunicorn worker/two threads on loopback 8000; host restricts access and provides HTTPS |
| `make demo` / `make demo-smoke` | Original fixture demo with explicit / simulated source review |
| `make demo-proof OUTPUT=/tmp/payproof-proof-new` | New artifact-backed Acme report |
| `make benchmark-heldout-validate` | Frozen definitions/protocol only; no predictions |
| `.venv/bin/python -m payproof.heldout_benchmark --evaluate-gold --output /tmp/payproof-gold-new` | Gold evaluation; currently FAIL; no model |
| `.venv/bin/python scripts/smoke_live_extraction.py` | Environment-configured small live synthetic smoke |
| `.venv/bin/python -m payproof.heldout_benchmark --live --output /tmp/payproof-live-new` | Configured live pipeline; no fixture substitution |
| `.venv/bin/python scripts/check_credential_history.py` | Value-free reachable history; findings need owner triage |

`workflow --help` lists durable commands. Held-out output directories must be new. Gold and CLI exit statuses never authorize payment.

### Configuration

Process environment is authoritative; the local launcher used by `make serve` loads ignored `.env` defaults without shell evaluation. Library/test calls do not load it automatically. `.env.example` is an empty credential/model template. Supply secrets privately through the host environment; never commit or paste them into source, documents, URLs or logs.

| Variable | Default / requirement |
| --- | --- |
| `PAYPROOF_ENV` | `development`; also `test`/`production` |
| `PAYPROOF_PORT` | `8000`, ASCII digits, 1024–65535 for local server |
| `PAYPROOF_DATA_DIR` | `./data`, private persistent SQLite directory |
| `PAYPROOF_EXTRACTION_MODE` | `disabled`; `fixture` matches exact bundled development text; `live` needs key/model |
| `PAYPROOF_PROVIDER_API_KEY` | Absent; server-only; never reuse exposed history |
| `PAYPROOF_PROVIDER` | `openai` default; use `featherless` for chat completions |
| `PAYPROOF_PROVIDER_BASE_URL` | Official HTTPS `/v1` API root matching selected provider |
| `PAYPROOF_PROVIDER_MODEL` | Exact selected provider model ID; no default or guessed ID |
| `PAYPROOF_EXTRACTION_TIMEOUT_SECONDS` | `30`, ASCII digits, 1–60 |
| `PAYPROOF_SECRET_KEY` | Absent; random 32+ characters for production/operator workflow |
| `PAYPROOF_OPERATOR_TOKEN` | Absent; distinct random 32+ character passphrase plus signing secret for operator pages |

Unknown `PAYPROOF_*`, invalid values, missing live key/model and missing production signing secret reject startup with sanitized errors. Health initializes neither storage nor provider. Production cookies require HTTPS. CSRF, same-origin checks, strict forms, escaped evidence, CSP, no-store pages, expected revisions and configured-secret guards protect the writable workflow. Operator labels are attribution, not proof of individual identity or an actual callback.

Live Featherless configuration and current foundation limits: [provider boundary](docs/PHASE3_PROVIDER_AND_FOUNDATION.md). Local `make serve` loads ignored `.env` through `scripts/run_local.py`; process environment wins. `make verify` runs all gates and retains failures without overwriting saved benchmarks.

### Public workspace

Start at the browser landing page: **VERIFY A PAYMENT REQUEST**. Establish A: previously trusted information, then provide B: the new request. Baseline uploads/extraction remain untrusted drafts until explicit human source/prior-trust/contact assertions. Public workspaces use separate temporary stores and never expose private operator records. Use synthetic/test data only; sessions expire after 30 minutes of inactivity and access ends on restart.

Anonymous live extraction is off by default. Enable `PAYPROOF_PUBLIC_LIVE_ENABLED=true` only with live mode/key/model and a chosen `PAYPROOF_PUBLIC_LIVE_MAX_CALLS` lifetime allowance (default20, shared and durable across sessions/restarts). Current Featherless access remains unverified after HTTP403. The secondary Acme sample is labeled DEMO EXAMPLE and uses fixtures. Details: [public isolation, workflow and limits](docs/PUBLIC_WORKSPACE.md). `/healthz` is liveness; `/readyz` is local storage/configuration readiness and does not probe the provider.
