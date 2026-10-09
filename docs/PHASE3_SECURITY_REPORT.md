# Phase-3 anonymous-workspace security review

Assessment: **PARTIAL**. Anonymous isolation, safe extraction failure, revision-bound human actions and bounded provider use have executable synthetic/mocked evidence. No P0 was found in the tested paths. Three public-demo P1 implementation defects and one high-value P2 were fixed. Historical credential status remains an owner-dependent potential P1 release blocker. This review does not certify security, public deployment, model robustness or financial safety.

Reviewed on2026-10-09, starting commit `e8d0abe38d6ef2ce8dcae60cb0687a764cc619f3`, branch `master`; worktree already contained the optional-example changes. No credentials were rotated, Git history rewritten, accounts created or application deployed. Source schemas, comparison semantics, extraction grounding, safety states and frozen benchmark labels were preserved.

## Scope and evidence classes

Tests exercise the real mounted Flask workflow and real SQLite persistence with synthetic sources. Live-provider success/error responses are **MOCKED**, and example observations are **SYNTHETIC/REPLAYED**. The model adapter receives sources only, never the baseline/contact. Strict local schema and exact source validation remain mandatory. `UNCHANGED`, `VERIFY`, `UNCERTAIN` are the only comparison states. A separate `VERIFIED` attestation requires an explicit independent human action and current bound revisions; neither the model nor comparison can create it. No payment authorization exists.

Forty new tests are in `tests/test_phase3_security.py`. Existing suites include `test_public_workspace.py`, `test_demo_examples.py`, `test_phase2_redteam.py`, `test_redteam.py`, `test_instruction_safety.py`, `test_persistence.py`, `test_live_extraction.py` and `test_featherless.py`. These are not measurements of real-model prompt-injection resistance. A real malicious model is still treated as untrusted output; source inventory cannot prove exhaustive intent discovery.

## Reproduced findings and fixes

Failing tests were added before the four fixes. The focused pre-fix run had5 failures (two exercise duplicate-call reservation). Its original output is saved as `benchmarks/phase3-security/regression-before.txt`.

| Finding | Severity | Observed before | General fix | Residual risk |
| --- | --- | --- | --- | --- |
| Active session database removed by another visitor's cleanup | P1 integrity/reliability | Gallery activity renewed session access but not directory mtime; another session deleted that still-active store | Cleanup skips all active IDs under the registry lock | Inactive deletion remains opportunistic; restart expires anonymous access; host backups are outside retention guarantees |
| Anonymous non-extraction writes/reads unbounded | P1 public resource abuse |40 authenticated malformed mutations all reached workflow processing; no shared mutation ceiling | Session, peer-IP and global read/write burst ceilings;128 writes/session lifetime | Distributed visitors can still exhaust shared allowance or cause availability loss; health/static routes are not a general DDoS shield |
| Production workflow accepted plaintext | P1 transport/configuration | HTTP workspace returned200 despite Secure-cookie configuration | Require secure WSGI scheme for public/private workflows before form/session access; explicit HTTPS error | Deployment must correctly restrict/trust the TLS proxy; host HTTPS is not automatically configured |
| Simultaneous duplicate live submissions spend twice | P2 bounded cost/reliability | Both concurrent copies entered the mocked provider before submission persistence | SQLite atomically claims the operation UUID and spends one invocation before provider access | Crash consumes the claim; no automatic retry/refund; new independent submissions spend again within the global cap |

The first full-suite run was846 passed/1 failed: an existing production-cookie test expected HTTP login. It was updated to assert HTTP rejection and check cookies over HTTPS. The production requirement was not relaxed. Original runner evidence remains under `/tmp/payproof-phase3-security-final-20261009`; final evidence is recorded separately below.

## Attacks and outcomes

| Attack | Current observed outcome | Severity if bypassed / residual |
| --- | --- | --- |
| Cross-session case/draft/vendor/receipt access, guessed IDs, six mutation actions | Other session's DB is used; no owner revision/event changes; private operator records remain inaccessible | P0/P1 bypass not reproduced; possession of a session cookie is possession of that temporary workspace |
| Tampered authoritative fields, foreign revisions, invalid transitions | Unknown/duplicate form fields rejected; server assigns contact/time/state; review/comparison prerequisites enforced | P0 bypass not reproduced; human assertions are not independently authenticated identities |
| Repeated submit and live extraction; concurrent provider calls | Persisted duplicates return original result; in-flight duplicate operation gets429, one provider call; explicit new operation subject to all caps | Cost bound verified with mocked responses, not real provider billing |
| Cookie/IP churn and fake `X-Forwarded-For` | Durable total cannot reset with cookies/restart; four distinct live submissions with changing forwarded IP yield3 calls then429 | IP limits use the peer; proxies may share one conservative allowance |
| Prompt injection asking VERIFIED/approval, extra model verdict fields | Extra fields/malformed output fail strict extraction; no human event or fallback | P0 bypass not reproduced; model may still extract incorrectly within a valid schema |
| Omitted changed account, old/current history, footer/multiple accounts, contradictory documents | Independent source inventory exposes competing regions; omission/review cannot establish unchanged; tested cases abstain UNCERTAIN | P0 bypass not reproduced; bounded lexical coverage is not proof of intent or completeness |
| Unicode lookalikes, OCR corruption, punctuation, zeros/tail collisions, invalid checksum | Full supported destination validation preserves identity; uncertain inputs are not repaired into equality | Unsupported GB/DE-external schemes/countries remain UNCERTAIN |
| Source/notes HTML or scripts; hostile filenames | Jinja escaping plus CSP; script content is visible text, not executable; filenames never select paths | Browser execution/mobile inspection not certified; no MIME attachments/PDF/MSG parsing |
| Oversized body, unsupported PDF, invalid UTF8, unexpected files | Rejected before provider reservation/persistence; no truncation-to-success |100k HTTP body,20k aggregate characters,16 sources; server/proxy must also bound connection abuse |
| CSRF, foreign Origin/Referer, duplicate token fields, logout replay | Token and origin checks fail; SameSite Strict cookies; logout revokes registry entry | Missing Origin alone is not rejected, but unpredictable token remains required |
| Stale tab/retry/trusted baseline, wrong expected revision | Stale request cannot spend another extraction or confirm prior comparison; revised baseline requires refresh/review/comparison | Full snapshot/current engine binding retained; host administrators remain trusted |
| Concurrent/duplicate human verification | Two simultaneous public submissions yield one302 and one409; one event; replay of winning action is idempotent | VERIFIED remains a human assertion, never payment approval or account ownership |
| Malformed model JSON, fabricated evidence, unknown state, partial output | Strict schema/grounding failure closes safely; missing remains missing; no independent verification | Evidence validation does not establish the truth of source claims |
| Provider timeout/outage/network failure | Explicit unsuccessful extraction, sources retained, no reviewable decisive evidence; comparison UNCERTAIN; no fixture fallback | Socket I/O timeout is not an absolute full-call deadline; no retries |
| Budget DB migration, restart, simultaneous claims | Legacy counter retained;8 concurrent same-operation reservations have one winner; count/claim survive restart | Administrator can alter/delete DB; rate/session registries are process-local |
| Application restart with old browser cookie | Old cases inaccessible; new temporary workspace starts empty | Public workspaces have no durable recovery; private persistence is separate |
| Debug/errors, echoed configured secrets, secrets pasted into source | Debug disabled; generic storage/errors; configured secret rejected before provider/storage; provider echo not retained | Unknown/encoded secrets and host/access/provider logs are not comprehensively scanned |
| Production configuration abuse | Missing production signing secret, invalid cap/live config, insecure provider root and unknown DEBUG setting rejected | Requires valid deployment configuration and correctly restricted upstream; multiworker public sessions unsupported |

## Exact anonymous controls

No login was added. Public live extraction is off by default and requires live configuration plus `PAYPROOF_PUBLIC_LIVE_ENABLED=true`.

| Limit | Implemented ceiling |
| --- | --- |
| Active temporary sessions |64/process;30-minute inactivity expiry |
| New sessions |4/peer-IP/minute |
| Workflow GET reads |120/session/minute;240/peer-IP/minute;480/global/minute |
| Workflow mutating POSTs |30/session/minute;60/peer-IP/minute;120/global/minute |
| Authorized writes per session lifetime |128; malformed attempts and duplicate posts count |
| Example case creation |12/session/minute |
| Extraction attempts |6/session/minute; live additionally3/peer-IP/minute |
| Shared live provider budget |Durable lifetime1–100 invocations, default20, configured by `PAYPROOF_PUBLIC_LIVE_MAX_CALLS` |
| Provider payload limits |20k input characters,16 sources,262144 response bytes,8000 output tokens |

Budget counter and operation claims share one `BEGIN IMMEDIATE` transaction in `public-live-budget.sqlite3`, outside disposable session stores. Failed calls and crash reservations count. No anonymous reset endpoint exists. UUID claims are session-scoped and contain no source text/contact/credential. Baseline extraction, case creation and case-revision extraction paths all reserve before provider access. Cookie clearing and restart do not refund usage. Global cap exhaustion returns429 without a provider call; synthetic examples remain separately available. Logout remains possible at the write ceiling; history remains readable subject to read limits.

This limits invocation count, not dollars. Provider pricing, credits and billing limits are UNKNOWN. New distinct submissions can deliberately consume the shared allowance. Use one Gunicorn worker/two threads as the repository command specifies; more workers make process-held sessions inconsistent. Rate registries are bounded but reset on restart; the shared provider ledger does not. An owner-controlled reset/increased cap is a deliberate billing decision.

Production workflow requests must be HTTPS as represented by the WSGI server. No blind `ProxyFix` or user-supplied forwarded-IP trust was introduced. Gunicorn recognizes TLS scheme headers only from allowed peers; default trusted addresses are loopback. The TLS proxy must strip incoming spoofed scheme headers, send its own marker and keep Gunicorn inaccessible directly. Configure only the real proxy peers; do not blindly allow all. Liveness/capability routes remain available for local HTTP probes. Host TLS and external URL checks are still required.

## Secrets and owner blocker

The existing `scripts/check_credential_history.py` ran successfully and exited2 (**FINDINGS**, not a scanner crash):29 reachable commits,376 unique blobs,0 binary exclusions,2 finding blobs. Safe metadata is saved in `benchmarks/phase3-security/credential-history.json`.

- `tests/test_release_gates.py`: confirmed synthetic private-key header used to test the scanner; no private-key body.
- Historical `.env.example`, first reachable commit `b20f37d5596ee44e8eb41c00465ee04d16c7b500`: nonempty secret-assignment candidate. Current private configured credential does not match that historical literal. Neither difference nor an earlier provider403 proves historical revocation.
- Owner response during this review: **Unknown — needs checking**. Treat this as a potential P1 before public release. Zeeshan must determine whether the old value was real; if real, revoke/rotate it in the issuing provider's dashboard and configure replacement securely in ignored local/host secret configuration. Report status only, never a credential. If synthetic, record that determination. Clearing an example/history does not revoke a key. No automatic history rewrite was performed.

Exact current configured-secret matching found no occurrence in working public source/artifacts or HEAD tracked blobs. Root `.env` is ignored/untracked and contains the provider key privately. Public examples remain blank. `current-secrets.json` records statuses only. This is not proof against arbitrary, encoded, unreachable or externally copied secrets. TruffleHog was not required or introduced.

## Verification and benchmark results

Final commands and actual output are saved in `benchmarks/phase3-security/verification.json`, with new diagnostic/held-out outputs beside it. Previous/frozen benchmark artifacts were not overwritten.

| Check | Result | Evidence class |
| --- | --- | --- |
| New adversarial tests |40 PASS |SYNTHETIC + MOCKED provider |
| Complete suite |847 PASS,0 fail,0 skipped |Synthetic/fixture/mocked, real Flask/SQLite |
| Lint, formatter, strict typecheck |PASS;41 source files |Executable tooling |
| Configuration, frozen protocol |PASS |Local configuration; no provider request |
| Wheel/sdist + installed smoke/migration/restart |PASS |Existing pinned interpreter dependencies; offline application-wheel install |
| Production socket under workspace sandbox |BLOCKED, EPERM |Execution environment, not PayProof failure |
| Authorized installed Gunicorn loopback |PASS health200; HTTP workspace403; trusted TLS marker workspace200/Secure cookie |Synthetic configuration; simulated trusted proxy, not public HTTPS |
| History scan |FINDINGS, exit2; owner triage BLOCKED |Reachable Git pattern scan |
| Real-provider adversarial/live benchmark |NOT RUN; successful live access still unverified after earlier Featherless403 |No real-model result claimed |

| Reviewed GOLD benchmark | Diagnostic | Held-out definitions |
| --- | --- | --- |
| Overall strict result |FAIL |FAIL |
| Cases |30 |72 |
| Correct state |28/30 |56/72 |
| Exact state/reasons/values/evidence |28/30 |53/72 |
| Known changes / correct VERIFY |13 /8 |24 /12 |
| Changed UNCERTAIN abstentions |5 |12 |
| Critical false UNCHANGED |0 |0 |
| False VERIFY |0 |0 |
| Exact uncertain handling |13/13 |30/33 |
| Comparison scoring failures / failed operations |2 /0 |19 /0 |
| Extraction metrics |NOT_RUN |NOT_RUN |

These counts are unchanged from pre-security artifacts. Held-out gold mismatch stems from conservative competing-instruction abstention and additive unsupported-identifier reasons; it remains FAIL. Abstention is not successful change detection. No labels, scoring, normalization or comparison were altered to improve metrics. No gold/live/replay headline is pooled.

Reproduce without private credentials:

```bash
.venv/bin/python -m pytest -q tests/test_phase3_security.py
.venv/bin/python scripts/check_credential_history.py
# Exit2 means findings need triage; the output contains no secret values.
.venv/bin/python scripts/verify_foundation.py /tmp/payproof-security-new-run
# Use a new directory. Both gold gates currently fail; subsequent gates still run.
.venv/bin/python scripts/check_wheel.py --http
# Exit2 if binding is platform-blocked. No live AI call is made.
```

## Remaining risks and release decisions

P0 open in tested paths: **0 found**, not proof of absence. Public-demo P1 code findings: **0 open** after fixes. Potential historical credential P1: **1 unresolved owner-dependent finding**. Public HTTPS/proxy configuration and external provider behavior remain unverified; this review cannot sign off a deployed service.

Before public deployment: resolve the historical credential status, securely configure a strong distinct production signing secret, verify HTTPS/proxy/upstream restriction from an external network, keep public live disabled until real grounded extraction succeeds and deliberately fund/cap any enabled public calls. Current private local configuration contains a provider credential but no production signing secret; test-only synthetic settings do not substitute for host configuration.

This remains a synthetic hackathon workspace, not a real-organization pilot. Anonymous attribution is not authentication; a human can falsely attest that they called. There is no organizational access control, encrypted-at-rest/backup guarantee, guaranteed deletion, centralized abuse protection or production monitoring. A shared allowance can be exhausted for denial of service. The lexical instruction inventory cannot prove intent or catch all unrecognized corruption/omissions. Model injection testing here is mocked contract enforcement. Provider account/privacy/billing and public browser/mobile security have not been validated. Existing gold failures and independent label review remain visible.
