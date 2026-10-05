# PayProof benchmark specification

Version: `payproof-phase1-diagnostic-30-v1`. Rule version: `iban-gb-de-v1`.

**Status: harness implemented; measured diagnostic runs recorded; independent label review PENDING.**
Observed results are stored in [run artifacts](../benchmarks/phase1-v1/results/README.md), separately from these frozen expectations. The design dataset retains its original `NOT_RUN` marker: it contains no predictions or performance measurements. Contract tests validate the dataset; the harness executes and scores the product.

## Claim and scope

Test this claim: can PayProof detect consequential changes between newly requested payment instructions and a manually selected, previously trusted vendor revision, preserve their evidence, and require independent human verification?

Evaluate destination comparison, extraction fidelity, uncertainty, and the human-action boundary. Do not assign fraud, legitimate-vendor, bank-ownership, or payment-safety labels. A legitimate bank migration is still a changed destination. `UNCHANGED` establishes only supported identifier equality; it is not permission to pay.

Keep the [architecture](ARCHITECTURE.md) and [comparison rules](COMPARISON.md) frozen. Phase 1 compares complete GB/DE IBANs, including bank/routing/account components encoded inside them. It accepts ASCII grouping spaces and ASCII case changes. Separate routing instructions, other countries, dashes, and Unicode separators require `UNCERTAIN`. A bank **display label** changing alone is contextual; a receiving-bank code changing inside an IBAN changes the destination. These boundaries are tested, not silently widened to improve a score.

## Dataset and ground truth

The machine-readable dataset is [cases.json](../benchmarks/phase1-v1/cases.json), with [JSON Schema](../benchmarks/phase1-v1/schema.json) and strict [Pydantic contracts](../payproof/evaluation_contracts.py). JSON Schema checks shape; Pydantic also checks source digests, exact excerpts/offsets, source chronology, vendor bindings, normalized annotations, and cross-record consistency. Unknown properties, including invented performance results, are rejected. Validation reuses canonical application contracts; it is not an independent performance oracle.

Each case contains:

- Immutable synthetic source text, source kind, SHA-256, IDs, and timestamps; the contradictory pair contains both original sources.
- A referenced synthetic trusted vendor revision, previously verified callback provenance, and full trusted identifier. Missing history is genuinely `null`, with an explicit manually selected vendor ID.
- Authored gold observations for all canonical extraction fields, including raw candidate values, statuses, exact excerpts and Unicode character offsets. Missing/unreadable fields have no invented value or quote.
- An optional canonical requested identity where normalization is supported. No repaired account is supplied for corrupt or incomplete text.
- Destination truth, changed components with old/new values, contextual changes, scope boundary, and a rationale.
- Expected state/reasons after simulated **gold source review**, and separately without source review.
- Explicit non-destination spans for historical or irrelevant account-like numbers, so a perfectly quoted wrong-role extraction can still be scored as wrong.

All vendors, contacts, institutions, and identifiers are synthetic. Supported examples have valid GB/DE layouts and MOD-97 checksums; these do not assert bank existence or account ownership. The FR example tests unsupported-country handling, not French national banking validity. Gold attribution is `FIXTURE`, never a purported live model or real human verification.

Ground truth is authored from the source construction and trusted revision **before predictions**. Do not derive it from PayProof's output, a model's confidence, or a successful source quote alone. Component labels describe synthetic identifier structure, not an external bank-directory lookup. Invoice amount/number changes are authored prior-invoice context; those are not fields added to the trusted vendor contract.

`destination_relation` has three evaluation-only values:

- `CHANGED`: construction establishes at least one consequential difference. Some such cases are outside Phase-1 comparison support and must abstain.
- `UNCHANGED`: the author copied the destination; representation or contextual text may change. Unsupported formatting can still require abstention.
- `UNRESOLVED`: the actual current destination or trusted counterpart cannot be established from supplied evidence. Do not invent an intended account or a changed/unchanged label.

Coverage families are not outcome labels. There are 12 true-change-family cases, 8 no-change-family cases, and 10 uncertainty-family cases, with overlapping adversarial tags. Actual truth is 13 changed, 9 unchanged, and 8 unresolved. Expected reviewed states are 10 `VERIFY`, 7 `UNCHANGED`, and 13 `UNCERTAIN`. These are dataset counts, not measured results.

## Frozen case inventory

Every expected result below assumes successful, accurately grounded extraction and complete simulated gold source review. All 30 cases **without source review** expect `UNCERTAIN` and `REVIEW_REQUIRED`; existing blockers remain, with `BASELINE_UNAVAILABLE` first for PP-27. The JSON specifies every ordered reason list.

| ID | Synthetic scenario and destination truth | Expected state | Reviewed reason |
| --- | --- | --- | --- |
| PP-01 | GB account component 3821 → 9928; **changed** | VERIFY | DESTINATION_CHANGED |
| PP-02 | Different full GB account retains the trusted 3821 suffix; **changed** | VERIFY | DESTINATION_CHANGED |
| PP-03 | DE routing component 00110011 → 00110012, account fixed; **changed** | VERIFY | DESTINATION_CHANGED |
| PP-04 | DE embedded routing and account both change; **changed** | VERIFY | DESTINATION_CHANGED |
| PP-05 | GB receiving-bank code TEST → MOCK, account fixed; **changed** | VERIFY | DESTINATION_CHANGED |
| PP-06 | GB bank, routing and account components all change; **changed** | VERIFY | DESTINATION_CHANGED |
| PP-07 | Separate routing 001101 → 001102, IBAN fixed; **changed, unsupported** | UNCERTAIN | UNSUPPORTED_DESTINATION |
| PP-08 | Account plus separate routing change; **changed, unsupported** | UNCERTAIN | UNSUPPORTED_DESTINATION |
| PP-09 | Plausible bank migration, verbose reason, expressly retired old account; **changed** | VERIFY | DESTINATION_CHANGED |
| PP-10 | Reordered invoice text with a new account; **changed** | VERIFY | DESTINATION_CHANGED |
| PP-11 | Unusual table layout with a new account; **changed** | VERIFY | DESTINATION_CHANGED |
| PP-12 | Irrelevant trusted-looking lookup identifier and extra numbers beside new instructions; **changed** | VERIFY | DESTINATION_CHANGED |
| PP-13 | Exact full identifier match; **unchanged** | UNCHANGED | DESTINATION_MATCH |
| PP-14 | Invoice amount alone changes 1250.00 → 5900.25; **unchanged destination** | UNCHANGED | DESTINATION_MATCH |
| PP-15 | Invoice number alone changes BENCH-001 → BENCH-777; **unchanged destination** | UNCHANGED | DESTINATION_MATCH |
| PP-16 | ASCII U+0020 grouping spaces inserted; **unchanged** | UNCHANGED | DESTINATION_MATCH |
| PP-17 | ASCII identifier/context capitalization changes; **unchanged** | UNCHANGED | DESTINATION_MATCH |
| PP-18 | Vendor display-name whitespace/punctuation changes; **unchanged destination** | UNCHANGED | DESTINATION_MATCH |
| PP-19 | Bank display label renamed, all identifier components fixed; **unchanged** | UNCHANGED | DESTINATION_MATCH |
| PP-20 | Dashes inserted into copied identifier; **unchanged, invalid representation** | UNCERTAIN | DESTINATION_INVALID |
| PP-21 | No current account supplied; **unresolved** | UNCERTAIN | DESTINATION_MISSING |
| PP-22 | Two conflicting, equally current account instructions; **unresolved** | UNCERTAIN | DESTINATION_AMBIGUOUS |
| PP-23 | Masked account characters; **unresolved** | UNCERTAIN | DESTINATION_INCOMPLETE |
| PP-24 | Explicitly unreadable account region, no readable characters; **unresolved** | UNCERTAIN | DESTINATION_INCOMPLETE |
| PP-25 | Full-looking identifier with invalid checksum; **unresolved, no repair inferred** | UNCERTAIN | DESTINATION_INVALID |
| PP-26 | Email and invoice give different current accounts, no precedence; **unresolved** | UNCERTAIN | DESTINATION_AMBIGUOUS |
| PP-27 | Current valid account but no trusted history; **unresolved** | UNCERTAIN | BASELINE_UNAVAILABLE |
| PP-28 | OCR-like O in a digit-only account component; **unresolved, no repair inferred** | UNCERTAIN | DESTINATION_INVALID |
| PP-29 | GB baseline to distinct FR-prefixed destination; **changed, unsupported** | UNCERTAIN | UNSUPPORTED_DESTINATION |
| PP-30 | Nonbreaking U+00A0 space inserted into copied identifier; **unchanged, invalid representation** | UNCERTAIN | DESTINATION_INVALID |

The 17 supported comparable cases are PP-01–06, PP-09–19: 10 changed and 7 unchanged. Known changes outside support are PP-07, PP-08, PP-29. Unsupported representation controls PP-20/30 are not extraction or comparison false positives when they correctly return `UNCERTAIN`.

## Evaluation tracks

Record and report tracks separately; never blend gold/manual corrections into live extraction accuracy.

1. **Gold comparison:** supply authored gold observations and explicitly simulated gold source review to the deterministic engine. Score state, ordered reasons, complete destination equality/difference, missing information, contradictions, and referenced evidence. No AI runs. Labels enter the scorer only after the engine returns. Simulated review is not independent bank verification.
2. **Extraction:** give the configured extractor only source documents, under the production prompt/schema. Do not provide baselines, expected outcomes, gold observations, exclusion annotations, or case-specific hints to the model. Score its original validated observations before human edits. Retain failed attempts as failures. Score exact raw values, missing/unreadable statuses, distinct current candidates, roles, and grounding.
3. **Review gate:** compare successful extraction before human source acknowledgement. Every case must remain `UNCERTAIN / REVIEW_REQUIRED` (plus other blockers). This measures the gate, not change-detection recall: an always-unreviewed workflow cannot demonstrate destination detection.
4. **Conditional pipeline diagnostic:** after validation, simulate review of the model's own observations, without gold correction, using a clearly labeled `SIMULATED_MODEL_OUTPUT_REVIEW` evaluation event. Use ordinary canonical review bindings; do not bypass validation, select between conflicting accounts, or force a normalized identity for invalid text. This deliberately tests what happens if a reviewer accepts the extraction. It exposes PP-09/12 wrong-role matches that exact-quote checks alone cannot prevent. A failed extraction remains failed/unresolved. This is a test protocol to implement later, not an assertion that a real person reviewed a source or a production auto-review option.
5. **Actual human workflow:** if evaluated later, independently record source-review acknowledgement, decline/correction, and displayed callback/action instructions. Corrections require a newly attributed extraction/review snapshot and a separate score. Measure correction effort and remaining workflow errors; do not credit corrected observations to the AI. Independent callback verification and any human-created `VERIFIED` record are separate from these comparison tests.

The current contracts cannot prove that the operator actually read the whole source. State this limitation with conditional pipeline results. Inspect rendered results as well as enums: `VERIFY` must explain the change, quote the new instruction, identify old provenance, and direct the operator to the previously trusted callback. `UNCERTAIN` must block resolution and request the specific missing clarification/trusted history. A source-review click is not independent verification.

## Metrics and definitions

Always publish numerator/denominator, case IDs, track, and per-state confusion counts, including a distinct `FAILED` outcome. Use `N/A` for undefined rates, not zero. Timeouts, schema rejection, or skipped attempts must not disappear from denominators. Until runs exist, observed metrics are `NOT_RUN` or `null`, never guessed zeros.

### Highest priority: consequential changes missed without requiring verification

**Critical false negative:** a case whose construction truth is `CHANGED` produces `UNCHANGED`, or the workflow otherwise presents a resolved/approval-like outcome allowing the changed destination to bypass independent verification. This includes reusing a stale matching result after an error and a `VERIFY` screen that allows completion without the required independent-check action. Count each affected case once and record all defects.

- Critical miss rate = critical misses / **13 known consequential changes**.
- Report the same counts for **10 supported changes** and **3 changes outside support**.
- For engine-only runs, false `UNCHANGED` is the measurable state proxy; mark human-action enforcement `NOT_EVALUATED` until that workflow exists. Do not infer workflow safety from enum accuracy.

`UNCERTAIN` is safe abstention only if it blocks resolution and requires clarification followed by a new comparison or independent trusted-source check. It is **not successful change detection or completed verification**. A fail-closed error is not a critical miss, but is an availability failure and fails exact-result scoring. No result, an ambiguous display, or an error must never be interpreted as permission to proceed.

### Detection and utility

| Metric | Definition |
| --- | --- |
| Supported change detection recall | Correct `VERIFY` with the right complete destination difference and evidence / 10 supported changed cases. `UNCERTAIN` and failures are misses for this detection metric. |
| Safe escalation rate | Known changed cases with actionable `VERIFY` or blocking `UNCERTAIN` / 13. Fail-closed operation errors are reported separately, not counted as successful escalation. |
| Supported match resolution | Correct `UNCHANGED` with complete matching identity and evidence / 7 supported unchanged controls. |
| False-positive rate | Incorrect `VERIFY` / 9 author-known unchanged destinations. Report supported controls (7) separately from unsupported formatting controls (2). |
| Unnecessary escalation | `VERIFY`, `UNCERTAIN`, or failure on the 7 expected-`UNCHANGED` controls / 7, broken down by outcome. |
| Exact case correctness | Correct state, ordered reasons, destination result, required missing/conflict records, and evidence references / 30. A correct enum with the wrong value or wrong-role evidence is incorrect. |
| Decision coverage | Definitive results on the 17 comparable cases / 17, reported alongside their correctness; no credit for decisive results on blocked cases. |
| Operational availability | Completed valid results / attempted cases, with failure/skipped counts and failure codes. |

For false positives, a bank display rename alone must not produce `VERIFY`. Correct policy-driven `UNCERTAIN` for dashes/Unicode is not a false positive. Unknown-truth cases cannot enter changed/unchanged false-negative or false-positive denominators; their unsafe resolution is scored separately.

### Uncertainty quality

Measure against the **13 expected-`UNCERTAIN` cases**, not every author-unknown case alone:

- Uncertainty recall = expected-uncertain cases returned `UNCERTAIN` / 13.
- Uncertainty precision = expected-uncertain cases returned `UNCERTAIN` / all returned `UNCERTAIN`; undefined if none are returned.
- **Informative uncertainty rate** = expected-uncertain cases with `UNCERTAIN`, correct blocker/reasons, all existing consequential candidate/conflict evidence preserved, no invented account, and specific actionable resolution guidance / 13. Report reason/evidence correctness and display-guidance correctness separately until the latter is tested.
- Unsafe definitive result rate = any `UNCHANGED` or `VERIFY` on expected-uncertain cases / 13. Both violate the current blocker policy, even if `VERIFY` is fail-safe with respect to payment.
- Unnecessary abstention = `UNCERTAIN` on the 17 comparable cases / 17. Operational errors remain separate failures.

An always-`UNCERTAIN` system can have zero false `UNCHANGED` and high uncertainty recall. It fails supported change recall, match resolution, precision, and coverage. Safety and utility must pass together.

### Extraction fidelity and evidence

Report field-level precision/recall for supported **current** consequential values, missing/unreadable-status accuracy, distinct-candidate ambiguity recall (especially PP-22/26), and unsupported-format preservation. Retain per-field counts so a hundred correct contextual values cannot drown out one lost destination.

A value is correctly extracted only when its raw string occurs in the source, its field and current-payment role are correct, and its evidence refers to the correct immutable source and exact supported excerpt/location. Claims about changed details require literal supporting text. Empty fields are not populated from the baseline. Compare canonical values only when scoring deterministic normalization; the AI must not silently normalize/repair its raw account observations.

Accept equivalent exact excerpts around the same correct observation; do not require identical gold quote boundaries. The production extractor may retain one representative of an identical repeated literal, so do not penalize that permitted deduplication. It must preserve distinct competing current instructions and both conflicting sources. Duplicate candidates resolving to the same full supported identity are not unresolved destination ambiguity. A quote of a retired identifier or lookup number is grounded text but the wrong payment role.

Report fabricated/unsupported consequential value count, exact-evidence validity count, omitted distinct current candidates, and wrong-role selections independently. Invalid response/schema/quote failures count as failed extraction and failed detection/utility, while safely rejected output is distinguished from an accepted invented value.

## Error taxonomy and attribution

Multiple errors can apply to one case. Record stage, primary cause, all categories, field, source/evidence IDs, and whether the error was accepted or safely rejected.

| Extraction category | Examples |
| --- | --- |
| `FIELD_OMISSION` | New current account, route, or change claim omitted |
| `SPURIOUS_VALUE` | Invented account/currency, baseline value filled into an absent source field |
| `WRONG_FIELD` | Invoice/telephone/lookup number extracted as account |
| `WRONG_ROLE` | Historical or explicitly retired account treated as current |
| `RAW_VALUE_ALTERATION` | Digit changes, stripped dashes/Unicode, guessed O→0 repair |
| `AMBIGUITY_LOSS` | One of two competing current accounts silently dropped |
| `EVIDENCE_MISGROUNDING` | Invented excerpt, bad offset/hash, wrong document, value absent from quote |
| `STATUS_MISCLASSIFICATION` | Missing versus unreadable confused, unsupported format presented as inferred certainty |
| `SCHEMA_ATTRIBUTION_ERROR` | Invalid types/extra verdict fields, false model/source attribution |
| `PROVIDER_FAILURE` | Timeout, unavailable service, truncated/invalid structured response; retain subtype |

| Deterministic/workflow category | Examples |
| --- | --- |
| `NORMALIZATION_COLLISION` | Different full identifiers collapsed through suffix/zero removal |
| `UNSAFE_REPAIR` | Punctuation/lookalike/checksum corrected without a supported rule |
| `FALSE_MATCH` | Correct changed canonical identity produces `UNCHANGED` |
| `FALSE_DIFFERENCE` | Valid grouping/case or contextual-only change produces `VERIFY` |
| `WRONG_GATE_PRECEDENCE` | Decisive result despite a missing/invalid/unsupported blocker |
| `UNSUPPORTED_FIELD_IGNORED` | Separate routing silently excluded from the uncertainty gates |
| `AMBIGUITY_DROPPED` | Distinct candidates accepted as one reviewed destination |
| `BASELINE_BINDING_ERROR` | Wrong vendor/revision, missing history replaced, untrusted source promoted |
| `REVIEW_GATE_BYPASS` | Decisive result before explicit complete source review |
| `RESULT_EVIDENCE_INCONSISTENCY` | Wrong reasons, incomplete difference, missing contradiction/source refs |
| `FAIL_OPEN` | Failed operation reuses old result, absence interpreted as approval, mandatory action bypassed |

A gold-comparison failure localizes a deterministic/contract bug. If gold comparison passes but original extraction is wrong, attribute the extraction error without calling it a comparator false match. Correct extraction with a wrong subsequent result is normalization/comparison/orchestration failure. Errors introduced or concealed by human correction belong in the separate human-workflow track. Preserve both root cause and end-to-end consequence: an extraction omission can cause a critical false `UNCHANGED` even when the comparator correctly evaluates its incomplete observations.

## Run protocol, freezing, and acceptance

1. Have a second reviewer independently inspect sources, baseline provenance, candidate roles, full values, unknown truth, and expected reasons. Review is currently **PENDING**; do not claim independence merely because this specification requested an evaluation-engineer role.
2. Before predictions or optimization, freeze the corpus version and file SHA-256, source digests, labels, rule version, prompt/schema hashes, model/provider version, application commit and dirty-tree diff, and evaluation protocol. Resolve label disputes before runs. Any later correction gets a new dataset version and written reason; preserve old predictions. Never relabel failures to improve a score.
3. Run the gold-comparison track and review-gate track; record every case outcome. Run configured live extraction and the conditional pipeline separately if authorized/configured. Do not silently substitute fixtures, mocks, or corrected gold input for live extraction.
4. Store an actual run manifest and predictions separately from this design dataset. Include run ID/time, exact corpus hash, track, configuration, source/review attribution, case IDs, failures/skips, original observations, results, and measured metrics. Keep credentials out of artifacts. Record latency/cost only if measured, with accounting method; no assumed prices or invented timing.
5. Report raw counts and case-level failures, including supported versus unsupported strata. Repeated model runs describe variability and do not increase the number of independent cases. Report skipped runs explicitly.

Proposed diagnostic acceptance targets, to be applied to actual runs:

- Zero critical misses among all 13 known changes; no falsely resolved `UNCHANGED` on any blocked case and no model/comparator-created `VERIFIED` or payment-safety verdict.
- Gold comparison: all 30 states, reasons, and required evidence/result content correct; all 10 supported changes detected and all 7 supported matches resolved.
- Review gate: all successful unreviewed extractions remain uncertain; invalid/failing operations fail closed.
- For a live-extraction demonstration claiming this suite passes: the conditional pipeline must also detect all 10 supported changes, resolve all 7 supported matches, and handle all 13 blocked cases with correct uncertainty and grounded evidence. A failed extraction is not a passing expected-uncertainty case. Report field-level errors even when they do not change the state.

These are proposed acceptance rules, not results. If live extraction fails the safety gate, use the explicitly human-reviewed fixture/manual demonstration and report the limitation, as the architecture requires. Do not weaken labels or accept universal abstention as successful detection.

This corpus is **public diagnostic development data**, not held out. It does not replace the architecture's independently reviewed 36-case release corpus with 12 unseen cases, four per outcome. Create genuinely unseen release cases and keep them away from prompt tuning; exposure to these published sources disqualifies them as held out. Small, related synthetic samples cannot establish population reliability, adversarial completeness, banking validity, or real-world fraud performance. No fraud precision/recall should be reported.

## Commands and current implementation status

Validate the new design contracts and reject malformed definitions:

```bash
.venv/bin/python -m pytest -q tests/test_benchmark_design.py
```

That command validates definitions only. Run the implemented harness:

```bash
make benchmark
make benchmark-extraction
.venv/bin/python -m payproof benchmark --replay benchmarks/phase1-v1/results/extraction/report.json
```

`make benchmark` runs all 30 cases on gold observations and separately checks the unreviewed gate; it ignores provider configuration and cannot call a model. `make benchmark-extraction` additionally attempts all sources using explicit environment configuration. It never expands fixture lookup to the new gold labels. Disabled extraction produces 30 `NOT_CONFIGURED` failures, not passing uncertainty classifications. Live mode needs the existing provider key/model settings; keys never enter run artifacts. `--replay` consumes stored original extraction observations/failures without extraction/provider calls, checks corpus/rule binding and complete case coverage, and reruns comparison/scoring.

The [harness](../payproof/benchmark_harness.py) produces `report.json` and `summary.txt` in `--output`, with per-case results, original observations, simulated review attribution, field scores, source evidence, stage-specific issues, integer count/fraction metrics, corpus/code/prompt/schema hashes, source Git revision and dirty-tree metadata. The report's `passed` flag applies only to requested tracks, not release readiness. Python version and pinned dependency/code hashes record execution context. Raw provider response bodies are not committed; their hashes are retained when available. Attempt latency is measured (including validation, not just provider time), while provider cost remains `null` because the adapter does not measure billed usage.

Exit 0 means all requested tracks passed; 1 means at least one evaluated case/track failed; 2 means corpus/replay/configuration could not be loaded. Scoring errors identify exact case IDs, field and extraction/comparison stage. Exceptions are captured per case using sanitized type names, so one provider or engine failure cannot remove the remaining cases. Failed operations enter the confusion matrix as `FAILED`, even if a fail-safe `UNCERTAIN` result was produced. Identical golden predictions and replayed observation scores are reproducible; fresh live model outputs and measured latency are not claimed deterministic. Compare `scoring_sha256` across replay runs rather than run timestamps or latency.

Detection counts require correct consequential values/evidence, independently of harmless contextual extraction errors; exact-case correctness additionally checks all extracted fields. Distinct competing instructions cannot be deduplicated; identical literal mentions and equivalent exact quote boundaries may be. Root-cause attribution keeps extraction-induced pipeline errors separate from errors on gold inputs. Human display guidance/action enforcement and independent verification remain `NOT_EVALUATED`; informative uncertainty metrics cover reasons and evidence only.

`tests/test_benchmark_harness.py` covers reproducibility, label isolation, per-case exceptions, correct-state/wrong-content failures, wrong-role false matches, missing configuration, context-error attribution, ambiguity, permitted duplicate mentions, replay hash/coverage rejection and CLI exit codes. The older ten-fixture runner is `python -m payproof benchmark-fixtures`. Independent label review and actual human-workflow evaluation remain pending.
