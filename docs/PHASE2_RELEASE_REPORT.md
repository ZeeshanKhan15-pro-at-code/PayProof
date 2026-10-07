# Phase-2 release-candidate verification report

Date: 2026-10-07. **Overall: PARTIAL.** The implemented persistent synthetic mechanism passes its executable safety/workflow checks. The strict gold evaluation gate is **FAIL**; clean installation, live extraction/evaluation, actual production HTTP and historical credential triage are **BLOCKED**. A complete release is not acceptable on this evidence, so the requested complete milestone commit and `phase2-freeze` tag are withheld. This is not security certification or production readiness.

## Status definitions and evidence

**PASS**: check executed and met its named expectation. **FAIL**: exercised expectation was violated. **BLOCKED**: required infrastructure/configuration/owner confirmation prevented completion. Existing dependencies are not a fresh install; WSGI/test-client health is not a real HTTP listener; gold/mocks/fixture demonstrations are not live extraction accuracy.

Artifacts under [benchmarks/phase2-freeze](../benchmarks/phase2-freeze/): [verification ledger](../benchmarks/phase2-freeze/verification.json), [clean install](../benchmarks/phase2-freeze/clean-install.json), [credential metadata](../benchmarks/phase2-freeze/credentials.json), [gold report](../benchmarks/phase2-freeze/gold/report.json), [gold summary](../benchmarks/phase2-freeze/gold/summary.txt), [blocked live attempt](../benchmarks/phase2-freeze/live-attempt.json). Raw pip/provider/test logs and secret values are not retained. The initial nonverbose pip failure summary is also preserved; verbose diagnosis establishes its final BLOCKED classification, rather than alleging an unavailable pin.

## Final gate ledger

| Gate | Status | Actual evidence / limit | Reproduction |
| --- | --- | --- | --- |
| Clean pinned setup/install | **BLOCKED** | Fresh venv without system-site dependencies created; pinned install exit 1. Verbose transport flags show DNS/network failure; index DNS probe `gaierror`, errno -3. Application install not reached. Existing interpreter matches all 28 pins separately. | Fresh `python3 -m venv /tmp/payproof-clean-new`; its Python `-m pip install --no-cache-dir --retries 0 --timeout 5 -r requirements-dev.txt`, then `-m pip install --no-build-isolation --no-deps -e .` |
| Environment/configuration validation | **PASS** | Current development/disabled configuration valid. Tests reject unknown settings, invalid ports/timeouts, missing live key/model, missing production signing key and credential reuse/reflection. Empty model template restored. | `.venv/bin/python -m pytest -q tests/test_skeleton.py tests/test_live_extraction.py tests/test_phase2_redteam.py` |
| No committed active credentials | **BLOCKED** | Current tracked pattern scan finds only the intentional synthetic private-key header test, no exposed value in the current template. Reachable history contains a nonempty credential-like `.env.example` literal. Its validity/revocation is not known. Pattern absence cannot prove no active credential. | `.venv/bin/python scripts/check_credential_history.py` |
| Ruff lint | **PASS** | Exit 0 in final ledger | `.venv/bin/ruff check .` |
| Formatting | **PASS** | Exit 0, Ruff format check | `.venv/bin/ruff format --check .` |
| Strict typecheck | **PASS** | mypy exit 0 | `.venv/bin/python -m mypy` |
| Complete tests | **PASS** | **754 passed** in final full synthetic suite | `.venv/bin/python -m pytest -q` |
| CLI initialization | **PASS** | Contract/fixture checks initialize without provider calls | `.venv/bin/python -m payproof check` |
| Persistence initialization and restart | **PASS** | `workflow init` twice in a new private directory; schema v1 idempotent. Tests and installed-wheel smoke persist/reload sources/revisions/events and reject unknown/broken schemas. | Set private `PAYPROOF_DATA_DIR`, run `.venv/bin/python -m payproof workflow init` twice |
| Live adapter/extraction contract | **PASS — mocked only** | Controlled responses exercise actual request/strict schema/exact evidence validation, missing/partial data, forbidden verdicts and no fallback. This is implementation coverage, not live readiness. | `.venv/bin/python -m pytest -q tests/test_extraction.py tests/test_live_extraction.py` |
| Real live extraction smoke | **BLOCKED** | Disabled mode, no key/model; `NOT_CONFIGURED`, exit 2, zero provider calls | `.venv/bin/python scripts/smoke_live_extraction.py` after private environment configuration |
| Provider failure behavior | **PASS — mocked only** | Timeout, network/provider/model errors, empty/malformed/duplicate/schema-invalid/fabricated output and secret echoes fail explicitly; no decisive/verification state | Full extraction/live/operator/red-team tests above |
| Frozen held-out definitions/protocol | **PASS** | 72 definitions and compile/hash checks unchanged; predictions NOT_RUN for validation command | `.venv/bin/python -m payproof.heldout_benchmark`; `.venv/bin/python scripts/compile_heldout.py` |
| Independent label review | **BLOCKED** | PENDING; no external human review recorded | Independently review source roles/exclusions/labels before any release-performance claim; do not silently edit v1 |
| Held-out reviewed gold comparison | **FAIL** | 56/72 states, 53/72 exact, 19 scoring failures, exit 1; all failures preserved | `.venv/bin/python -m payproof.heldout_benchmark --evaluate-gold --output /tmp/payproof-freeze-gold-new` |
| Held-out/live pipeline | **BLOCKED** | Configured live benchmark attempted; exit 2, zero provider calls/completed live cases; metrics NOT_MEASURED | `.venv/bin/python -m payproof.heldout_benchmark --live --output /tmp/payproof-freeze-live-new` after private live configuration |
| Seeded end-to-end web workflow | **PASS — synthetic request tests** | Acme 3821→9928 and original bundled seed: source/evidence → explicit review → VERIFY/DESTINATION_CHANGED → prior trusted callback → separate explicit human action/history; controls included | `.venv/bin/python -m pytest -q tests/test_operator_web.py tests/test_demo_proof.py` |
| Human verification invariants | **PASS** | No AI/comparison VERIFIED; only explicit current human confirmation; contact comes from baseline; comparison preserved; uncertain/failure/unreviewed cases reject | Full workflow/persistence/schema/red-team suites |
| Stale/revision/concurrency protections | **PASS** | Stale IDs/baseline/contact/engine updates reject; refresh requires review/compare; concurrent confirmation has one winner; rollback/idempotency preserved | `.venv/bin/python -m pytest -q tests/test_persistence.py tests/test_phase2_redteam.py` |
| Production build/package | **PASS with existing pinned dependencies** | Wheel/sdist, environment-file exclusion, offline temporary-target installation outside checkout, packaged migrations/templates/CSS/fixtures/Acme paths, console entry point | `.venv/bin/python -m build --no-isolation`; `.venv/bin/python scripts/check_wheel.py` |
| Production HTTP startup | **BLOCKED** | Installed package passes smoke, then socket creation `PermissionError`, errno 1, exit 2. No real listener result claimed. | `.venv/bin/python scripts/check_wheel.py --http` on a host allowing loopback sockets |
| Health endpoint | **PASS — production WSGI** / **BLOCKED — actual HTTP** | Installed production `/healthz` returns 200 in request tests; actual listener cannot start here. Health is liveness only, no database/provider initialization. | Same installed package/HTTP command |
| Architecture/documentation consistency | **PASS with explicit limits** | README describes implemented persistence/gated UI/human events and actual scores; architecture separates original plan from implementation and unmet gates; live docs remove stale credential-bootstrap claims. No mechanism/contracts/ground truth changed. | Review README, ARCHITECTURE, DATA_MODEL, LIVE_EXTRACTION, WEB_WORKFLOW and current handoffs |

All command return codes/statuses are retained. No failing benchmark prevented running the later build/HTTP/live stages. The older `make verify` stops at its diagnostic failure before build; final verification used explicit stages to cover every gate.

## Gold evaluation and risk priority

Dataset `payproof-phase2-heldout-72-v1`; corpus SHA-256 `203a43619b2baaf516063e5f2add4ce86a828c8ac8dc6c1e29edb6e09363c2d0`; reviewed track uses **SIMULATED_GOLD_SOURCE_REVIEW**. Extraction metrics NOT_RUN; real human-review/verification performance NOT_EVALUATED. This synthetic corpus does not establish real-world reliability.

| Reviewed gold metric | Actual |
| --- | --- |
| Cases / correct states / exact cases | 72 / 56 / 53 |
| Consequential changes / correct VERIFY detections | 24 / 12 |
| Changed cases missed as correct VERIFY | 12, all abstained UNCERTAIN |
| Critical false UNCHANGED / false VERIFY | 0 / 0 |
| Strict correct uncertainty / state-only recall | 30/33 / 33/33 |
| Comparison scoring failures / failed operations | 19 / 0 |
| Overall status | FAIL |

State/reason failures: PP-17–20, PP-41–48, PP-65–68 (conservative ambiguity abstention against expected decisive states). Reason-only failures: PP-57, PP-58, PP-60 (additional DESTINATION_INVALID with UNSUPPORTED_DESTINATION). No labels, evidence requirements, normalization or comparison semantics were relaxed. Resolve evaluation disputes through independent source-role/label review and versioned future protocol, not editing frozen outcomes after predictions. The unreviewed gate remains FAIL: 72/72 states, 53/72 exact cases. Do not promote that score to a combined accuracy headline.

Critical false UNCHANGED is the highest-priority safety metric; zero observed gold misses is not proof against extractor omissions. The separate adversarial omission regressions test the known P0 class. Changed-case abstention still misses strict VERIFY recall and remains visible as a utility/evaluation failure.

## Severity and open findings

- **P0 open: 0 known reproduced implementation defects.** The tested historical/current omission weakness was fixed previously; final regressions pass. Unrecognized instruction/discovery weaknesses remain possible, not certified absent.
- **P1 implementation defects open: 0 known reproduced.** Previously fixed session/secret/state/revision issues remain covered.
- **P1 release risk open: historical credential status unconfirmed.** An owner question was issued without requesting the value. If genuine, revoke/rotate it; if synthetic/already revoked, record that confirmation. Local blank fields/history scanning do not revoke a key. No credential validity test, history rewrite or key recovery was attempted.
- **P2 known**: conservative gold utility/reason mismatches; incomplete lexical/role discovery; socket-only provider timeout; duplicate case-create/provider cost; process-local rate/session registry; validator changes can refuse old unsafe snapshots; no later migration/retention tooling or stronger identity. No broad feature work was added to hide these limits.

## Changes for this release-candidate assessment

Corrected README's obsolete read-only/no-database/verification claims and historical headline scores. Cleared the unvalidated `.env.example` model default for the fixed adapter. Marked original architecture phase allocation as history and documented actual bounds: no inline selection editor, transient provider bytes, no later migrations/retention interface, human-action-only idempotency. Updated live configuration/evidence notes and created the requested handoffs. Saved current real verification/gold/blocked-live evidence without raw logs or credentials. No P0/P1 mechanism defect was reproduced requiring an engine/schema change; no new product feature or benchmark optimization was implemented.

## Freeze disposition and next steps

**PARTIAL means a reviewable release candidate, not a completed release.** The requested `milestone: phase 2 hardened PayProof complete` commit and `phase2-freeze` tag are withheld until the failed/blocked acceptance gates have a documented resolution. No deployment, credential revocation or history rewrite is implied.

Phase 3 begins by closing clean pinned setup on an unrestricted host, actual Gunicorn/health, historical credential triage and privately configured live smoke/held-out evaluation. Independently review the 19 gold mismatches without weakening competing-evidence abstention. Then address narrow provider deadline/retry/retention needs and functional presentation polish. Preserve strict evidence, prior callback provenance, deterministic state authority and explicit revision-bound human actions.
