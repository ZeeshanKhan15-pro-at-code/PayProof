# Phase-2 adversarial review

Date: 2026-10-07. This review used synthetic records, generated non-production credentials, controlled provider responses, direct Flask requests and concurrent SQLite connections. It is not security certification or a production-readiness declaration. No live model accuracy or real independent callback is claimed.

## Reproduced findings and fixes

| Attack | Observed before fix | Severity | Fix | Residual risk |
| --- | --- | --- | --- | --- |
| Extract only a 2020/reference account; omit a new account with separated country/bank letters or a zero-width country separator; submit an incorrect broad source acknowledgement | Three initial probes and two later truncated/split probes returned `UNCHANGED` instead of abstaining. The region included a different supported destination or a malformed competing destination. | **P0 unsafe outcome** | Detect separated GB/DE-shaped structures, including suspicious Unicode whitespace, format controls, letters/digits. Preserve raw observations/context. Explicit remit/send-funds/pay-to regions also retain malformed instructions even without a complete recognized identifier. The existing deterministic gate now returns `UNCERTAIN`. Normalization is unchanged and does not repair Unicode. | Lexical discovery is not exhaustive; arbitrary OCR corruption, opaque schemes and unrecognized instruction roles can still evade it. Human review cannot be replaced by these tests. |
| Replay copied signed cookie after logout | Evidence index remained accessible (200); clearing the browser cookie did not revoke its copy. | **P1 access-control defect** | Bounded process-local active-session registry revokes on logout and enforces idle expiry. | Stolen active cookies remain credentials until revocation/expiry. An already authorized request can remain in flight. One worker/process is required. |
| Rotate operator passphrase while retaining signing key; replay old cookie against restarted application | Old session remained accepted without knowing the new passphrase. | **P1 access-control defect** | Per-process gate epoch and active-session checks reject every pre-restart cookie. | Rotation requires restarting the running app; no live configuration reload or distributed session store is implemented. |
| Submit a configured credential with escaping characters in independent-check notes | Guard scanned `str(request.form)`, which escaped the value; positive record and notes were stored. | **P1 secret-retention defect** | Shared guard checks actual nested string values before web/CLI writes and display, including archive reads. Form values are checked individually. | Guards know current literal configured credentials, not every encoded, transformed or revoked historical secret. Existing contaminated archives may block display and need private recovery. |
| Place signing/operator secret in public provider-model configuration | Settings accepted it; metadata could expose it or send it as a model identifier. | **P1 configuration defect** | Reject every configured credential inside model configuration. | Unknown credentials cannot be recognized by equality checks; environment ownership remains trusted. |
| Use standalone extraction with signing/operator secret in source; malicious completion echoes operator secret as model/raw metadata | Source could reach the provider, and echoed metadata/raw response could be returned. Three additional tests failed before the core guard was applied. | **P1 extraction/retention defect** | Check all configured credentials before provider access and check completion metadata/raw JSON before retention. Echo fails `INVALID_RESPONSE`, raw bytes absent. | No broad secret-discovery guarantee. Provider/network failure remains separate from extraction accuracy. |
| Reuse provider API credential as session-signing secret | Misconfiguration was accepted, crossing credential roles. | **P1 configuration defect** | Reject shared signing/provider credential; existing operator-secret distinctness remains. | Key entropy and actual revocation are operational duties, not certified by validation. |
| Attach unexpected multipart file fields to non-upload actions | File fields were ignored despite the strict-form boundary. They could not substitute the callback or affect the comparison. | **P2 boundary inconsistency** | Reject unexpected file fields on every form; case creation alone allows the declared upload field. | Request-size limits are conservative; supported content is still bounded UTF-8 text. |

Initial regression batch: **13 instances, eight failed and five passed before fixes**. Separately, three core extraction-secret probes and one signing/provider-role probe failed before their fixes. A follow-up pair of truncated/split destination probes also failed after the first fixes and before adding explicit remittance-region capture. An additional OCR-corruption regression passes after that extension. The full new regression file has **30 passing instances** after changes; not all 30 were executed against the original revision. [Sanitized audit](../benchmarks/phase2-redteam/regression-audit.json) retains only IDs/counts, not raw diagnostic inputs or credentials.

## Other attempted attacks and observed controls

| Attack family / probes | Observed result | Rank / residual risk |
| --- | --- | --- |
| Prompt injection instructing the model to return `VERIFIED`/`human_confirmed`; fake verdict fields in model JSON | Strict existing wire schema rejected the output as `INVALID_RESPONSE`; comparison abstained; no human event existed. | No new P0/P1 finding. A schema-valid omission remains possible and requires independent inventory/review. |
| Forwarded threads, quoted prior invoices, footer accounts, multiple invoices, fake previous-account prose, contradictory instructions, irrelevant numbers | Existing source/evidence regressions and added omission probes pass; discovered competing destinations cannot be discarded by confidence or acknowledgement. | P2 utility cost: irrelevant account-shaped text and historical-plus-current bundles can also cause abstention. No scoped role-resolution workflow was added. |
| Unicode lookalikes, zero-width/bidirectional controls, unusual whitespace, leading zeros, same-tail collisions, malformed identifiers | Canonical normalization is unchanged; complete supported identifiers retain zeros/full identity, and invalid values do not match. New discovery probes expose competing suspicious strings without repairing them. | P3 additional discovery coverage remains possible; invisible characters can impair human reading. No exhaustive Unicode/OCR claim. |
| Duplicate form/JSON fields, forged state/operator/confirmation/callback fields, wrong case revision IDs, unsupported actions, direct requests without UI checks | Unknown/duplicate fields rejected; typed bindings and server-controlled contact/operator fields enforced. Unauthenticated/CSRF/origin failures rejected. | No new P0/P1 finding. Shared gate and operator labels do not establish individual identity. |
| Missing review, missing acknowledgement, unresolved destination, failed extraction; confirmation using suspect contact override | Confirmation blocked. Contact/identity came only from the stored current trusted baseline and comparison. | No new P0/P1 finding; an actual independent call cannot be proven by a self-reported record. |
| Stale case/browser revision, trusted/contact changes, safety-engine changes | Stale writes rejected; old human attestations remain historical. Refresh clears current review/comparison and requires a new review/comparison. | P2: stronger validation can reject an old unsafe snapshot on reload; preserve the private original and create/recover a new case, never silently relabel history. |
| Simultaneous confirmations through two SQLite connections | One transaction committed; the other was stale. Exactly one positive event and one revision advance existed. | No new P0/P1 finding. Privileged host/database modification is outside application-level tamper resistance. |
| Identical repeated human submission and changed-payload retry | Identical action was idempotent, history stayed at four versions; changed retry rejected. Failed-write regression rolled back all confirmation/head/event writes. | P2 residual: case creation itself is not idempotent; repeated create requests can produce duplicate cases/provider costs, bounded by per-session burst limits. No payment can execute. |
| Timeout, provider error, incomplete output, fabricated excerpt, malformed/duplicate model JSON, empty output | Existing mocked integration tests plus new probes passed: explicit safe failures or `UNCERTAIN`, no fixture fallback in live mode, no successful source review after failed extraction. | P2 socket timeout is not a complete provider wall-clock deadline. No automatic provider retries or durable quota was added. |
| Invalid UTF-8, UTF-16-like uploads, unsupported files, oversized body/text, aggregate limits | Rejected without case creation or truncation. Browser CRLF capture and exact stored-source grounding tests remain passing. | P3 alternate encodings/OCR are intentionally unsupported. |
| HTML/script in source, evidence, notes; secret reflection in errors/metadata | Jinja escaping and restrictive CSP preserved inert evidence; sanitized handlers did not echo model/validator/SQL inputs. Configured-secret guards now cover web, CLI and core extraction boundaries. | P2 unknown/encoded/historical secrets are not comprehensively discovered. Test failure diagnostics can expose generated synthetic fixture values; raw test logs are not committed as artifacts. |

Coverage lives in `tests/test_phase2_redteam.py` plus existing `test_operator_web.py`, `test_persistence.py`, `test_instruction_safety.py`, `test_redteam.py`, `test_live_extraction.py`, `test_extraction.py`, `test_schemas.py` and deterministic comparison/normalization suites. Passing these probes does not establish completeness against arbitrary adversarial documents.

## Actual held-out benchmark rerun

Frozen corpus and protocol hashes validated: **72 cases**, independently authored before prediction, label review still **PENDING**. Labels, cases, scoring protocol, schema and comparison semantics were not changed. The before run was saved before fixes. Both runs use **gold extraction observations and simulated source review**, not a live model or real human-verification evaluation.

| Reviewed gold track | Before | After |
| --- | --- | --- |
| Total cases | 72 | 72 |
| Correct states | 56/72 | 56/72 |
| Exact state/reasons/values/evidence | 53/72 | 53/72 |
| Consequential changes | 24 | 24 |
| Changes detected as correct `VERIFY` | 12 | 12 |
| Changes missed as correct `VERIFY` | 12 | 12 |
| Changed cases abstained as `UNCERTAIN` | 12 | 12 |
| Critical false `UNCHANGED` | 0 | 0 |
| False `VERIFY` escalations | 0 | 0 |
| Correct uncertainty including required reasons | 30/33 | 30/33 |
| Deterministic comparison scoring failures | 19 | 19 |
| Failed operations | 0 | 0 |
| Extraction accuracy/failures | NOT_RUN | NOT_RUN |
| Overall exit/status | 1 / FAIL | 1 / FAIL |

The 19 reviewed-track scoring failures are unchanged: state/reason mismatches for PP-17–20, PP-41–48 and PP-65–68 (the guard abstains instead of the expected decisive result), plus reason-only mismatches for PP-57, PP-58 and PP-60 (observed additional `DESTINATION_INVALID`). These are retained evaluation gaps, not passing classifications. No labels were edited to hide them. The no-review track has **72/72 state matches**, but only **53/72 exact matches** and remains **FAIL** on the 19 reason mismatches; its “uncertain handled correctly” metric is 53/72 under the frozen strict criterion.

The [intermediate run](../benchmarks/phase2-redteam/intermediate-gold/summary.txt) is also preserved; it preceded the follow-up remittance-region fix. Artifacts: [BEFORE summary](../benchmarks/phase2-redteam/before-gold/summary.txt), [BEFORE report](../benchmarks/phase2-redteam/before-gold/report.json), [AFTER summary](../benchmarks/phase2-redteam/after-gold/summary.txt), [AFTER report](../benchmarks/phase2-redteam/after-gold/report.json). Supplemental extraction metrics are `NOT_RUN`; gold results were not substituted for live extraction results. The new P0 probes are separate synthetic omissions outside this corpus, demonstrating why zero gold critical misses is not a security guarantee.

The live held-out command was also attempted, exited **2**, and made **zero provider calls**: process extraction mode is disabled with neither a configured provider key nor a model. Live performance is **BLOCKED — NOT_CONFIGURED**, all live metrics **NOT_MEASURED**. See [sanitized attempt](../benchmarks/phase2-redteam/live-attempt.json). Configure live credentials privately in the process environment before a real run; no fixture fallback was used.

## Credential-history assessment

The read-only reachable-Git scan matched two blobs: historical `.env.example` with a nonempty credential-like literal and `tests/test_release_gates.py` with an intentional synthetic private-key header used to test the scanner. The latter is a test marker, not a discovered private key. Actual validity and owner revocation of the `.env.example` candidate are unconfirmed. If it was a real credential, revocation/rotation remains required; local cleanup cannot remove external copies or prove revocation. No value, excerpt or raw history dump is included in this report. Pattern scanning does not establish secret-free history.

## Reproduction and remaining limits

```bash
.venv/bin/python -m pytest tests/test_phase2_redteam.py -q --tb=no
make lint
make typecheck
make test
make build
.venv/bin/python -m payproof.heldout_benchmark
# Use NEW output directories; the harness refuses overwriting retained results:
.venv/bin/python -m payproof.heldout_benchmark --evaluate-gold --output benchmarks/phase2-redteam/reproduction-gold
.venv/bin/python -m payproof.heldout_benchmark --live --output benchmarks/phase2-redteam/reproduction-live
.venv/bin/python scripts/check_wheel.py --http
# Scanner emits metadata only, never credential values:
.venv/bin/python scripts/check_credential_history.py
```

Current full suite: **744 passed**. Lint, formatting, typecheck, build and installed-wheel migration/page/assets checks passed. The installed Gunicorn listener check was **BLOCKED** at socket creation (`PermissionError`, errno 1); its command exited 2. Production WSGI request tests passed, but no real listener result is claimed. Provider credentials were not used or copied from Git. The independent label review/live extraction gate, source-discovery completeness, scoped conflicting-instruction resolution, provider wall-clock deadline, duplicate case-create handling and historical credential revocation remain unresolved. Authentication is still one shared operator gate with process-local revocation; no multi-user identity, cryptographic audit protection, banking, payment execution or autonomous approval was introduced.
