# PayProof

Phase 1 is frozen as a local, synthetic CLI comparison prototype. See the [handoff](docs/PHASE1_HANDOFF.md) for the freeze checklist and [Phase-2 release gates](docs/PHASE2_RELEASE_GATES.md) for current installation, HTTP, credential and provider readiness evidence. The repository demonstrates the core mechanism; the complete persistent release described in the [architecture](docs/ARCHITECTURE.md) is unfinished.

### Problem

A business receives apparently legitimate payment instructions whose destination may differ from previously trusted vendor information. PayProof shows the change, its evidence and the previously trusted contact for independent human checking. It does not approve payment, classify fraud or establish bank-account ownership.

### Phase-1 architecture

One Python package contains bounded text capture, strict Pydantic contracts, structured extraction, exact source validation, conservative normalization, explicit human source review, deterministic comparison and CLI evidence display. Dependencies are pinned; Flask exposes read-only debug/liveness endpoints. There is no database or implemented verification command.

```text
selected trusted baseline -----------------------------------------+
                                                                   |
email/invoice/plain text -> extraction -> schema + source validation |
                                       -> display all source spans |
                                       -> human source review      |
                                       -> normalization/comparison-+
                                       -> state, reasons, differences,
                                          evidence, trusted callback
```

[DATA_MODEL.md](docs/DATA_MODEL.md) defines canonical contracts. [VERTICAL_SLICE.md](docs/VERTICAL_SLICE.md) describes the connected workflow. SQLite persistence, a writable operator interface and independent-verification events remain planned architecture components, not current capabilities. No architecture or comparison rule was changed for this freeze.

### AI role

AI proposes source-backed field observations only. The model receives source text, not the trusted baseline, and cannot select the vendor, infer trust, set a comparison state or impersonate a human. Unexpected verdict/confirmation fields, duplicate JSON keys, invalid schema, fabricated quotes and partial account tokens fail closed. Missing observations remain missing.

Extraction has explicit `disabled`, `fixture` and `live` modes. The seeded demo uses exact synthetic fixtures offline. The Responses API adapter has mocked integration coverage; live extraction accuracy is unmeasured. Arbitrary text and email/invoice pairs need a compatible configured live provider/model. No silent fixture fallback exists. See [EXTRACTION.md](docs/EXTRACTION.md) and [LIVE_EXTRACTION.md](docs/LIVE_EXTRACTION.md) for configuration, mocked integrations and actual smoke status.

### Deterministic safety layer

The pure comparator uses complete checksum-valid GB/DE IBANs. Only ASCII spaces and ASCII case are normalized. Leading zeros and full identifiers are preserved; punctuation, Unicode lookalikes, masked values and unsupported destinations are not repaired. Bank display names, amount, currency and sender context do not determine destination equality.

| State | Meaning |
| --- | --- |
| `UNCHANGED` | Complete reviewed supported destination equals the selected trusted baseline; no payment authorization |
| `VERIFY` | Complete reviewed supported destination differs; independent human verification required |
| `UNCERTAIN` | Missing, failed, unsupported, conflicting or unreviewed evidence prevents a reliable comparison |

Only explicit human independent verification could create a separate scoped `VERIFIED` record later. That command is not implemented. Typing `REVIEWED` acknowledges source review and does not verify the vendor or account. See [COMPARISON.md](docs/COMPARISON.md).

### Current benchmark

`make benchmark` runs the frozen [30-case diagnostic specification](docs/BENCHMARK_SPEC.md) and saves [JSON](benchmarks/phase1-v1/results/gold/report.json) and [readable results](benchmarks/phase1-v1/results/gold/summary.txt).

| Gold comparison metric | Actual count |
| --- | --- |
| Correct states and exact result agreement | 30/30 |
| Known consequential changes | 13 |
| Correct `VERIFY` detections | 10; all 10 supported changes |
| Changed cases not detected as `VERIFY` | 3; unsupported and returned `UNCERTAIN` |
| Critical changed cases falsely `UNCHANGED` | 0 |
| Unchanged cases incorrectly `VERIFY` | 0 |
| Expected uncertainty handled correctly | 13/13 |
| Deterministic-comparison failures | 0 |
| Unreviewed gold gate correct | 30/30 |

Gold reviews are explicitly simulated. [Recorded configured-extraction results](benchmarks/phase1-v1/results/extraction/summary.txt) contain 30 `NOT_CONFIGURED` failures, zero successful classifications and zero comparison failures. They do not measure live AI accuracy. Independent labels remain `PENDING`; this public diagnostic corpus does not satisfy the architecture's 36-case held-out release evaluation. See [run notes](benchmarks/phase1-v1/results/README.md).

### Current limitations

- Source quotes prove presence, not current-payment relevance or completeness. An extractor can omit a current account and quote a historical account; incorrect human review can then produce `UNCHANGED`. This is a retained red-team reproduction and blocks unattended/live reliability claims. Review every original instruction, not just the proposed account.
- The CLI runs in memory. Durable case history, authenticated review identity, cross-request current-revision checks and independent verification are absent. The read-only web server does not serve the payment workflow.
- GB/DE IBAN and UTF-8 plain text only. Separate routing, other schemes/countries, OCR, PDF ingestion and automatic vendor matching are unsupported. Conservative grounding can reject undelimited numeric columns or footnotes.
- Fixture success and mocked provider tests are not real-world extraction accuracy. Socket timeouts do not establish a complete provider wall-clock deadline.
- Tracked secret fields are empty and local `.env` files are ignored. A credential-like value existed in earlier Git history; owner revocation/rotation, if live, is still required. This freeze does not certify secret-free history or revoke credentials.
- Clean installation could not be completed here because package-index DNS access was blocked and the download approval service was unavailable. Existing-environment checks and package smoke validation are recorded separately in the handoff.

The [red-team report](docs/PHASE1_REDTEAM.md) records the fixes and residual risks. Phase 2 priorities and architecture discrepancies are listed in the [handoff](docs/PHASE1_HANDOFF.md).

### How to run

Requires Python 3.11+, `venv`, pip and GNU Make. First installation needs package-index access. From the repository root:

```bash
make verify
make demo
```

`make verify` installs pinned dependencies, runs lint/format checks, strict typecheck, all tests, initialization, gold benchmark and production package build with an actual temporary-target wheel installation and smoke validation using the invoking interpreter’s dependencies. `make demo` displays original text and extracted evidence before prompting. Read them and type `REVIEWED`; the full account changes from `GB46TEST00000000003821` to `GB57TEST00000000009928`, producing `VERIFY / DESTINATION_CHANGED`. The fixture, contacts and accounts are fictional.

| Command | Purpose |
| --- | --- |
| `make setup` | Create/update `.venv` with pinned dependencies |
| `make lint typecheck test` | Run configured quality checks |
| `make demo-smoke` | Offline seeded demo with explicitly simulated source review |
| `.venv/bin/python -m payproof demo --no-review` | Leave the demo `UNCERTAIN / REVIEW_REQUIRED` (exit 2) |
| `make benchmark` | Save the 30-case gold diagnostic run |
| `make benchmark-extraction` | Evaluate configured extraction; missing configuration is a failure |
| `make build` | Build wheel/source distribution and validate installed package contents |
| `make serve` | Read-only local server at `http://127.0.0.1:8000`; `/healthz` is liveness only |

The CLI also supports `check`, `debug`, `extract`, `analyze`, and `benchmark-fixtures`. The installed console command is `.venv/bin/payproof`. File analysis is described in [VERTICAL_SLICE.md](docs/VERTICAL_SLICE.md). Exit 0 means a completed supported comparison, exit 2 means uncertainty/invalid CLI usage, and exit 1 means an operation/configuration failure; none authorizes payment.

Process environment is authoritative; `.env` is **not automatically loaded**. Optional local configuration:

```bash
cp .env.example .env
# Edit the ignored local file; never commit credentials.
set -a
. ./.env
set +a
make debug
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `PAYPROOF_ENV` | `development` | `development`, `test`, or `production` |
| `PAYPROOF_PORT` | `8000` | Local `serve` port, 1024–65535 |
| `PAYPROOF_EXTRACTION_MODE` | `disabled` | `disabled`, `fixture`, or `live` |
| `PAYPROOF_PROVIDER_API_KEY` | Absent | Server-only provider credential, redacted in settings |
| `PAYPROOF_PROVIDER_MODEL` | Absent in process environment | Explicit model compatible with the fixed OpenAI Responses endpoint and structured output; example model text is not proof of compatibility |
| `PAYPROOF_EXTRACTION_TIMEOUT_SECONDS` | `30` | Provider socket I/O timeout, 1–60 seconds |
| `PAYPROOF_SECRET_KEY` | Absent | Production requires at least 32 nonblank characters, supplied independently |
| `PAYPROOF_DATA_DIR` | `./data` | Reserved data path; no database is created |

Unknown `PAYPROOF_*` variables and invalid settings fail startup. The demo ignores live configuration; initialization, gold benchmarks and replay never call the provider. Live `extract`, `analyze`, and extraction benchmarking send source text to the configured provider. Use synthetic data for demonstrations. `make production` runs Gunicorn on loopback port 8000 with a host-provided signing secret; it exposes the same read-only skeleton and is not a deployed verification workflow.
