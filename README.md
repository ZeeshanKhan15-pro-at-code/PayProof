# PayProof

A Phase-1 CLI prototype for human-reviewed payment destination comparison. Follow the frozen [architecture](docs/ARCHITECTURE.md) and [data contracts](docs/DATA_MODEL.md).

The project initializes offline after dependency installation. The [CLI vertical slice](docs/VERTICAL_SLICE.md) connects text capture, [structured extraction](docs/EXTRACTION.md), schema/evidence validation, normalization, explicit human source review, [deterministic comparison](docs/COMPARISON.md), and evidence display. Results are only `UNCHANGED`, `VERIFY`, or `UNCERTAIN`. Persistence, the web operator workflow, and independent human verification remain implementation targets.

Run the seeded **3821 → 9928** changed-account demo:

```bash
make demo
```

Read the displayed source/evidence and type `REVIEWED`. The result is `VERIFY / DESTINATION_CHANGED`, with both full accounts, old onboarding provenance, new exact instruction and the previously trusted callback. `make demo-smoke` runs the same synthetic pipeline with explicitly simulated source review; it uses no API key or network call. See [VERTICAL_SLICE.md](docs/VERTICAL_SLICE.md) for file analysis, optional email/invoice pairs, exit codes and limits.

## Initialize and prove it works

Requires Python 3.11+ with `venv`, pip, and GNU Make. Run from the repository root:

```bash
make verify
```

This creates `.venv`, installs pinned dependencies and the editable package, runs lint/format checks, strict typechecking, tests, application initialization, synthetic gold comparison, and the production package build. It also smoke-tests the built wheel in an isolated Python process outside the repository. The first setup requires package-index access; later verification uses the prepared environment. Re-run `make setup` when dependency configuration changes.

Checks stop on failure. Passing synthetic fixtures is a regression check, not proof of live AI accuracy or complete extraction of arbitrary requests.

## Useful commands

| Command | Purpose |
| --- | --- |
| `make setup` | Install/update the development environment |
| `make lint` | Ruff lint plus formatter check |
| `make format` | Apply Ruff fixes and formatting |
| `make typecheck` | Strict mypy across application source and packaging smoke script |
| `make test` | Run schema, normalization, comparison, extraction, CLI integration and startup tests |
| `make demo` | Seeded changed-account workflow with explicit source-review prompt |
| `make demo-smoke` | Seeded offline workflow with clearly labeled simulated source review |
| `make debug` | Print synthetic fixture names and implementation status |
| `make benchmark` | Compare labeled synthetic evidence with simulated reviews; emit JSON and fail on mismatch |
| `make serve` | Local read-only Flask server, bound to `127.0.0.1:8000` by default |
| `make build` | Build `dist/payproof-0.1.0.tar.gz` and `dist/payproof-0.1.0-py3-none-any.whl`; validate the wheel |
| `make production` | Run one Gunicorn worker on loopback port 8000; requires production signing secret |

The installed console command is `.venv/bin/payproof`; the equivalent module entry point is `.venv/bin/python -m payproof`. Both support `check`, `debug`, `benchmark`, `serve`, `extract`, `analyze`, and `demo`. `payproof analyze --vendor trusted-vendor.json --email email.txt --invoice invoice.txt` displays the full review/comparison flow; arbitrary files require configured live extraction. `payproof extract --email email.txt --invoice invoice.txt` emits only evidence JSON. See [the workflow](docs/VERTICAL_SLICE.md) and [extraction contract](docs/EXTRACTION.md) for modes, failures, exit codes, and limits.

`GET /healthz` reports process liveness only. `GET /` returns a small JSON capability summary. Neither serves source documents, bank identifiers, secrets, or write operations. The Flask interactive debugger and reloader are disabled.

## Configuration

Process environment is authoritative. No `.env` file is automatically loaded, and no signing secret is committed or generated as a default. Optional shell workflow for your own trusted local file:

```bash
cp .env.example .env
# Edit .env locally; keep real secrets out of source control.
set -a
. ./.env
set +a
make debug
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `PAYPROOF_ENV` | `development` | `development`, `test`, or `production` |
| `PAYPROOF_PORT` | `8000` | Local `serve` port, 1024–65535; the Makefile's Gunicorn target binds port 8000 |
| `PAYPROOF_DATA_DIR` | `./data` | Reserved SQLite/data directory; initialization does not create it |
| `PAYPROOF_EXTRACTION_MODE` | `disabled` | `disabled`, `fixture`, or `live`; no silent fallback |
| `PAYPROOF_SECRET_KEY` | Absent | Production requires an independently generated signing secret of at least 32 nonblank characters |
| `PAYPROOF_PROVIDER_API_KEY` | Absent | Server-only key for the OpenAI adapter; excluded from dumps/reprs |
| `PAYPROOF_PROVIDER_MODEL` | Absent | Explicit model supporting Responses API structured output; no guessed default |
| `PAYPROOF_EXTRACTION_TIMEOUT_SECONDS` | `30` | Provider socket I/O timeout, 1–60 seconds |

`fixture` extraction accepts only exact bundled synthetic source text/kind and labels the result `FIXTURE`. Debug/benchmark commands validate fixtures regardless of supported extraction mode. Generate production secrets on the host, for example using `.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))'`, and supply them through host secrets or the ignored local environment file. Settings dumps, reprs, and CLI validation errors omit secrets.

Unknown `PAYPROOF_*` variables and invalid settings fail startup. Configuration reads do not create a database, call a provider, or import credentials from files. Live mode requires a nonblank provider key and model. Initialization/debug/benchmark commands never call the provider, even with live credentials configured.

The current server has only nonsensitive read-only endpoints. A signing secret is preparation for the later operator session, not an implemented login gate. Add the operator gate and CSRF protection before creating document/verification routes. A production deployment of the eventual workflow also needs restricted HTTPS access and a persistent data volume, as required by the architecture.

## Repository layout

```text
payproof/
  config.py          validated environment settings; redacted secrets
  documents.py       bounded pasted-text capture with server metadata
  schemas.py         canonical Pydantic contracts and source/review bindings
  validation.py      typed JSON validation boundary
  normalization.py   conservative GB/DE IBAN and contextual normalization
  provenance.py      exact UTF-8 source digests
  extraction.py      source-grounded extraction and failure records
  extraction_contract.py private transport schema and prompt
  openai_extraction.py bounded standard-library HTTPS provider adapter
  comparison.py      pure source-bound decision engine; no AI or I/O
  cases.py           extraction, explicit review, comparison orchestration
  presentation.py    trusted/current values, exact evidence, and result display
  storage.py         reserved SQLite boundary
  verification.py    reserved human command boundary
  fixtures.py        synthetic loader and cross-record validation
  fixtures/
    trusted_vendors/ four synthetic trusted baseline/contact records
    requests/        ten source-grounded request/observation records
  benchmark.py       gold comparison with simulated synthetic source review
  web.py             read-only Flask factory
  cli.py             file analysis, seeded demo, extraction and offline tooling
  __main__.py        python -m payproof entry point
  py.typed           installed package typing marker
tests/
  examples.py        existing synthetic schema examples
  test_schemas.py    canonical-contract good/malformed cases
  test_normalization.py conservative representation and formatting cases
  test_comparison.py decisions, review gates, evidence, and collision checks
  test_skeleton.py   configuration, capture, corpus, and startup checks
  test_extraction.py ten requested scenarios and mocked provider/failure checks
  test_vertical_slice.py capture-to-display and CLI/pair/failure integration
scripts/
  check_wheel.py     isolated distributable-package smoke test
docs/                architecture, data model, extraction, comparison, CLI workflow
.env.example         variable names and empty secret placeholder
Makefile             one-command setup and verification
pyproject.toml       runtime/build/tool configuration
requirements-dev.txt pinned complete development environment
MANIFEST.in          source-distribution inclusions
```

Ruff also checks and formats tests. Strict mypy covers typed application/tooling source; deliberately malformed JSON test dictionaries remain dynamic test inputs. Existing schema/extraction tests remain regression gates for the comparator and narrowly refined duplicate-evidence review contract.

## Synthetic corpus and benchmark limits

All bundled vendors, contacts, labels, and account examples are fictional test data. They assert no real account ownership. Request records carry `FIXTURE` attribution and exact quotes/offsets; they do not contain source reviews, comparison results, or human verification records.

Fixtures cover exact match, formatted match, changed email, changed invoice, missing destination, conflicting instructions, unsupported IBAN country, Unicode lookalike, prompt injection, and the seeded 3821 → 9928 demo. Expected labels are developer-authored benchmark metadata describing the intended result **after valid human source review**; they are never copied into runtime comparison state.

`make benchmark` reports comparison agreement, mismatches, false `UNCHANGED` count, and elapsed time on all ten development fixtures. Reviews are explicitly simulated and never persisted as human attestations. Live AI evaluation remains `NOT_IMPLEMENTED`; mocked extraction tests are separate. The architecture's independently reviewed 36-case release corpus and held-out evaluation remain incomplete. See [COMPARISON.md](docs/COMPARISON.md) for exact rules and benchmark limits.

## Next implementation target

Add SQLite persistence, the gated web review workflow, and explicit independent human verification against the stored trusted contact/revision. Preserve snapshots across restarts and enforce stale-revision checks. Extend and independently label the release corpus. Separately smoke-test configured live extraction using synthetic data. The engine remains scoped to GB/DE IBAN; separate routing and other schemes require later explicit contracts.
