# Phase-2 release gates

Assessment date: 2026-10-05. Scope: installation, distributable package, HTTP health, configuration, historical credential exposure and provider readiness. The [Phase-1 handoff](PHASE1_HANDOFF.md) remains the freeze snapshot. Comparison semantics, canonical schemas, evidence/extraction contracts, safety states, architecture and benchmark labels are unchanged.

**Overall: PARTIAL.** The installed application package and in-process production initialization can be checked here. Clean dependency installation, actual HTTP listening and live provider readiness are not proven. Historical credential revocation needs owner confirmation.

`PASS` means the named check completed and met its expectation. `BLOCKED` means an external condition prevented the check or required confirmation; it is not an application failure. `FAILED` means an exercised expectation was violated. No blocked gate is counted as passing, and shared dependencies are never counted as a fresh installation.

## Gate ledger

| Gate | Previous status | Current status | Evidence | Remaining blocker | Exact reproduction command |
| --- | --- | --- | --- | --- | --- |
| Fresh installation of all pinned dependencies | BLOCKED | **BLOCKED** | New venv `/tmp/payproof-phase2-release-4wb2e5ds/clean` created without system-site packages. Pinned install exits 1 before application install. Sandbox DNS probe returns `gaierror: [Errno -3] Temporary failure in name resolution`; verbose pip diagnosis confirms `NewConnectionError` caused by `[Errno -2] Name or service not known` while connecting to the package index. The final “no matching distribution” message is not evidence that the pin is unavailable. Escalated wheel-download retry was not executed because automatic approval review's model was at capacity. Existing interpreter matches all 28 pinned versions, separately from clean installation. | Package-index access and a functioning approval service or a complete trusted wheelhouse. Dependency availability in a genuinely fresh host remains unverified. | `python3 -m venv /tmp/payproof-phase2-release-4wb2e5ds/clean` then `/tmp/payproof-phase2-release-4wb2e5ds/clean/bin/python -m pip install --disable-pip-version-check --no-cache-dir --retries 0 --timeout 5 -r requirements-dev.txt` |
| Production wheel installation and smoke | PARTIAL: direct zip import used existing dependencies | **PASS with existing pinned dependencies** | Updated smoke actually runs offline `pip install --no-index --no-deps --target` into a fresh temporary target outside the checkout. Installed origin and package metadata are asserted. Installed console entry point, all fixtures, seeded `VERIFY` demo and production WSGI health pass. Dependencies remain those of the invoking interpreter. | Clean dependency environment is the separate blocked gate above. This does not prove a clean production deployment. | `make build`; standalone `.venv/bin/python scripts/check_wheel.py` |
| Installed production HTTP binding and health | BLOCKED: in-process WSGI only | **BLOCKED** | `.venv/bin/python scripts/check_wheel.py --http` installs/smokes the wheel, then returns `http_binding=BLOCKED`, `reason=PermissionError`, `errno=1` on socket creation. No listener/process is left running. In-process production `/healthz` returns 200. | Sandbox denies socket creation with EPERM. The actual Gunicorn listener and real HTTP responses cannot be certified here. | `.venv/bin/python scripts/check_wheel.py --http` (exit 2 for platform denial, 1 for exercised failure) |
| Environment validation and production startup contract | PASS in Phase 1 | **PASS** | Disabled startup works; production without signing secret, live mode without key/model and unknown variables reject with sanitized `ConfigurationError`. Installed production WSGI uses a freshly generated ephemeral signing secret, debug disabled, secure cookie setting and read-only capabilities. Secret values are not output. Full suite result below. | None for validated configuration shape; provider compatibility remains separate. | `make test`; `.venv/bin/python -m pytest -q tests/test_skeleton.py tests/test_extraction.py` |
| Current tracked secret hygiene | PASS: blank example fields | **PASS** | Provider/signing secret fields remain blank; `.env` absent and ignored. No historical credential is reproduced in source, new reports or console output. No real key was used. | Historical exposure is not cured by a blank current file. | `.venv/bin/python -m pytest -q tests/test_redteam.py -k example_secrets` |
| Credential-history assessment and revocation | BLOCKED: earlier exposure known | **BLOCKED: owner confirmation required** | Value-free scanner examines all reachable refs including stash history: 16 commits, 147 unique blobs, zero binary blobs. One finding blob, `.env.example`, introduced in `b20f37d5596ee44e8eb41c00465ee04d16c7b500`, line 9: `NONEMPTY_ENV_SECRET_LITERAL`. Current example is cleared. | Revocation/rotation is required if genuine; the literal has no obvious placeholder marker or shell-variable reference. Treat it as exposed until its owner confirms it was synthetic or already revoked. No validity/revocation test or history rewrite performed. | `.venv/bin/python scripts/check_credential_history.py` (metadata-only JSON; exit 2 for historical findings, independent of external owner confirmation) |
| Configuration example readiness | Ambiguous: provider model example not validated against adapter | **PASS as an explicit empty template** | Removed the unvalidated nonblank model default. `.env.example` documents the fixed Responses endpoint and requires an explicitly compatible model. Extraction remains disabled by default. No provider, endpoint or contract added. | Actual compatible model selection and credentials remain necessary for live use. | `.venv/bin/python -m payproof debug` (does not load `.env.example` automatically); inspect the blank model placeholder locally |
| Live provider readiness | BLOCKED / no measured live accuracy | **BLOCKED / NOT ATTEMPTED** | Current process: extraction `disabled`, provider key absent, model absent, `.env` absent. Adapter remains fixed to `https://api.openai.com/v1/responses`, strict structured output. Existing mocked provider/failure integration tests remain the adapter evidence; no live request made. | Owner-supplied fresh provider credential, compatible explicit model, outbound network access, then a synthetic live extraction check. Never reuse the exposed historical value. | After host configuration: `.venv/bin/python -m payproof extract --email /tmp/payproof-provider-smoke.txt`; prepare exact synthetic input below |

## Evidence and changes

The previous package check proved that a wheel could be imported as a zip with the existing interpreter. It did not prove installation or console-script creation. The revised [check_wheel.py](../scripts/check_wheel.py) now installs the application wheel into a temporary target, rejects checkout imports, checks installed metadata and exercises the installed entry point. This closes the packaging-evidence gap without changing application logic.

Its optional `--http` starts one Gunicorn worker against the installed package in production mode, probes loopback `/healthz` and `/`, and terminates the process. It disables HTTP proxies for the loopback probe. EPERM/EACCES on the initial socket is `BLOCKED`; unrelated socket errors, Gunicorn startup failure, wrong health response and a ten-second health deadline are `FAILED`. The signing secret is ephemeral, generated in memory and never printed or committed. A successful health response establishes this read-only process's liveness, not extraction accuracy or payment verification.

The [history scanner](../scripts/check_credential_history.py) reports path, line, category and Git identifiers only. It does not print excerpts, hashes of individual credential values, prefixes or credentials. Findings are candidate exposures, not validity checks. It scans unique reachable historical text blobs for secret literals in environment files, common token shapes and private-key markers. Pattern scanning cannot certify absence; unreachable objects/reflogs, external copies and provider revocation are not checked. Test fixtures use generated synthetic tokens only. A history rewrite would not revoke a credential and was not performed.

Only `.env.example`, release-validation scripts/tests and documentation change. Existing comparison, normalization, schemas, extraction transport/prompt, architectural decisions and gold case definitions are preserved. The earlier wrong-role omission limitation remains documented in [PHASE1_REDTEAM.md](PHASE1_REDTEAM.md); these operational checks do not certify live extraction reliability or implement deferred verification/persistence features.

## Verification suite

Completed in the existing pinned environment on 2026-10-05:

- `make verify`: **exit 0**. Ruff lint/format passes (47 files), strict mypy passes (25 source files), **595 tests pass**, and CLI initialization passes without provider calls or a database.
- Gold benchmark saved under `benchmarks/phase1-v1/results/gold/`: 30/30 states and exact results, 10/10 supported changes detected, three unsupported changed cases abstained, zero critical false `UNCHANGED`, 13/13 expected uncertainty and zero comparator failures. Corpus digest remains `3bc6dcafaeb661b00cf22fd06fc86802c8db642c41d9228676faae3b546a0c7f`; scoring digest remains `b2b2e52c28855690e2a8a51f0fa8be847635cc2986adb82c825849d818cda67c`.
- Source distribution and wheel build pass. Actual wheel target installation reports `installed_and_initialized`, production WSGI health 200, four vendors/ten requests and installed console entry point `PASS`, using existing pinned dependencies. The seeded demonstration remains `VERIFY`; no authoritative `VERIFIED` is created.
- Optional package/HTTP probe produces the same successful installed-package observations and then `BLOCKED / PermissionError / errno=1` for sockets. History scanner exits 2 with one candidate exposure blob. Neither exit is counted as an application test failure or a passing release gate.
- Clean venv was created successfully; its dependency install is `BLOCKED` by transport DNS failure. No current dependencies were copied into it and no clean install is claimed. The download approval attempt failed before execution because its review model was at capacity.

Seven new release-tool regressions cover removed historical exposure with no value disclosure, empty/reference placeholders, private-key markers, skipped binary accounting, finding-command exit status, and BLOCKED-versus-FAILED socket classification. Existing safety/extraction tests remain intact. No P0/P1 defect in the proven application mechanism was found during these checks; the installation-evidence gap and misleading configuration example were corrected.

```bash
make verify
.venv/bin/python scripts/check_wheel.py --http
.venv/bin/python scripts/check_credential_history.py
```

The last two commands produce useful results with exit 2 when platform denial or history findings require resolution. `make verify` includes lint, formatter check, strict typecheck, all tests, application initialization, saved gold benchmark and the production build with installed-wheel smoke. It does not count the optional HTTP/history gates as automatically passing.

On a host with package-index access, use a genuinely new development environment:

```bash
release_venv="$(mktemp -d /tmp/payproof-clean.XXXXXX)"
make verify VENV="$release_venv"
```

For a clean production package installation using the complete pinned dependency set:

```bash
release_venv="$(mktemp -d /tmp/payproof-prod.XXXXXX)"
python3 -m venv "$release_venv"
"$release_venv/bin/python" -m pip install -r requirements-dev.txt
"$release_venv/bin/python" -m pip install --no-index --no-deps dist/payproof-0.1.0-py3-none-any.whl
cd /tmp
"$release_venv/bin/payproof" check
"$release_venv/bin/payproof" demo --simulate-review
```

This installs the complete pinned set, including development tools; it deliberately avoids an unpinned transitive runtime resolution. Run installation commands from the repository root before changing directory. It is a reproduction recipe, not a successful clean run recorded here.

To prepare a synthetic provider readiness input without supplying gold output to the model:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from payproof.fixtures import load_corpus
request = next(r for r in load_corpus().requests if r.fixture_id == 'demo-account-change')
Path('/tmp/payproof-provider-smoke.txt').write_text(request.source.text)
PY
# Configure PAYPROOF_EXTRACTION_MODE=live, a fresh provider key and compatible model
# through the host environment. Never paste credentials into commands or source.
.venv/bin/python -m payproof extract --email /tmp/payproof-provider-smoke.txt
```

Check exact source-backed account observations and attribution, not an AI verdict. Success is one readiness smoke, not benchmark accuracy. Live evaluation remains a separate explicitly configured `make benchmark-extraction` run; do not substitute gold fixtures or overwrite the saved failed extraction history to claim a pass.

## Remaining blockers

- Complete a clean pinned installation and application-wheel smoke on a host with package-index access or a complete trusted wheelhouse.
- Run the installed production HTTP/health probe on a host that permits loopback sockets.
- Obtain owner confirmation that the historical literal was synthetic or revoked; otherwise revoke/rotate the exposed credential before any use.
- Supply a fresh compatible provider configuration and validate a synthetic live extraction with network access. Live readiness and accuracy remain unmeasured.
