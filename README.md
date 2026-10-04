# PayProof

A Phase-1 repository skeleton for human-reviewed payment destination comparison. Follow the frozen [architecture](docs/ARCHITECTURE.md) and [data contracts](docs/DATA_MODEL.md).

The project initializes offline after dependency installation. It captures bounded pasted text, validates contracts and source evidence, normalizes supported GB/DE IBANs, loads synthetic fixtures, and exposes read-only debug endpoints. [Structured extraction](docs/EXTRACTION.md) is implemented with one optional live OpenAI adapter. Comparison, persistence, and human verification remain implementation targets; extraction produces no payment decision.

## Initialize and prove it works

Requires Python 3.11+ with `venv`, pip, and GNU Make. Run from the repository root:

```bash
make verify
```

This creates `.venv`, installs pinned dependencies and the editable package, runs lint/format checks, strict typechecking, tests, application initialization, corpus validation, and the production package build. It also smoke-tests the built wheel in an isolated Python process outside the repository. The first setup requires package-index access; later verification uses the prepared environment. Re-run `make setup` when dependency configuration changes.

Checks stop on failure. A successful fixture check is not proof of live AI extraction or destination-comparison accuracy.

## Useful commands

| Command | Purpose |
| --- | --- |
| `make setup` | Install/update the development environment |
| `make lint` | Ruff lint plus formatter check |
| `make format` | Apply Ruff fixes and formatting |
| `make typecheck` | Strict mypy across application source and packaging smoke script |
| `make test` | Run schema, skeleton, and mocked extraction integration tests |
| `make debug` | Print synthetic fixture names and implementation status |
| `make benchmark` | Validate source-grounded synthetic corpus; emit a JSON report |
| `make serve` | Local read-only Flask server, bound to `127.0.0.1:8000` by default |
| `make build` | Build `dist/payproof-0.1.0.tar.gz` and `dist/payproof-0.1.0-py3-none-any.whl`; validate the wheel |
| `make production` | Run one Gunicorn worker on loopback port 8000; requires production signing secret |

The installed console command is `.venv/bin/payproof`; the equivalent module entry point is `.venv/bin/python -m payproof`. Both support `check`, `debug`, `benchmark`, `serve`, and `extract`. For example, `.venv/bin/payproof extract --email email.txt --invoice invoice.txt` emits canonical evidence JSON; configured live mode sends the sources to OpenAI. See [the extraction contract](docs/EXTRACTION.md) for modes, failures, exit codes, and limitations.

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
  schemas.py         canonical Pydantic contracts; unchanged semantics
  validation.py      typed JSON validation boundary
  normalization.py   existing deterministic GB/DE IBAN validation
  provenance.py      exact UTF-8 source digests
  extraction.py      source-grounded extraction and failure records
  extraction_contract.py private transport schema and prompt
  openai_extraction.py bounded standard-library HTTPS provider adapter
  comparison.py      explicit deterministic-comparison placeholder
  cases.py           reserved case orchestration boundary
  storage.py         reserved SQLite boundary
  verification.py    reserved human command boundary
  fixtures.py        synthetic loader and cross-record validation
  fixtures/
    trusted_vendors/ three synthetic trusted baseline/contact records
    requests/        nine source-grounded request/observation records
  benchmark.py       initial corpus-validation runner
  web.py             read-only Flask factory
  cli.py             offline tooling and explicit text-file extraction
  __main__.py        python -m payproof entry point
  py.typed           installed package typing marker
tests/
  examples.py        existing synthetic schema examples
  test_schemas.py    canonical-contract good/malformed cases
  test_skeleton.py   configuration, capture, corpus, and startup checks
  test_extraction.py ten requested scenarios and mocked provider/failure checks
scripts/
  check_wheel.py     isolated distributable-package smoke test
docs/                frozen architecture and canonical data model
.env.example         variable names and empty secret placeholder
Makefile             one-command setup and verification
pyproject.toml       runtime/build/tool configuration
requirements-dev.txt pinned complete development environment
MANIFEST.in          source-distribution inclusions
```

Ruff also checks and formats tests. Strict mypy covers typed application/tooling source; deliberately malformed JSON test dictionaries remain dynamic test inputs. Existing schema tests remain the regression gate for the normalization module move.

## Synthetic corpus and benchmark limits

All bundled vendors, contacts, labels, and account examples are fictional test data. They assert no real account ownership. Request records carry `FIXTURE` attribution and exact quotes/offsets; they do not contain source reviews, comparison results, or human verification records.

Fixtures cover exact match, formatted match, changed email, changed invoice, missing destination, conflicting instructions, unsupported IBAN country, Unicode lookalike, and prompt injection. Expected labels are developer-authored benchmark metadata describing the intended result **after valid human source review**; they are never copied into runtime comparison state.

`make benchmark` reports schema/source validation counts and validation time. Comparison and live AI accuracy evaluation remain `NOT_IMPLEMENTED`; the extraction service's mocked integration tests are separate. These nine development cases are a starting corpus, not the architecture's 36-case release benchmark or held-out evaluation. Expand and independently label that corpus when the comparator and live extraction evaluation are implemented.

## Next implementation target

Implement the pure deterministic comparator and complete manual source-review path: exact reviewed destination plus frozen trusted baseline in, only `UNCHANGED` / `VERIFY` / `UNCERTAIN` with reasons and evidence out. Test the architecture decision table and extend the corpus, then add SQLite persistence and explicit human verification. Separately smoke-test configured live extraction using synthetic data. No polished UI is needed for that step.
