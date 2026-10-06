# Current-instruction safety: conservative source completeness gate

Implemented 2026-10-06. This addresses the reproduced path where extraction quoted a real historical trusted IBAN, omitted a different current destination, and a broad source-review acknowledgement allowed UNCHANGED. The initial 12 adversarial checks reproduced **10 failures and two passes** before changes. Additional regressions cover opaque destinations, same-tail collisions, bounded-inventory overflow, exact contexts and Unicode prefixes. The production extractor, its strict wire schema and its prompt are unchanged; no second model, role verdict or fraud score was added.

## Mechanism and trust boundary

`payproof/instruction_safety.py` independently inventories destination-like regions in every frozen source, across document order, forwarding history, quotation, footer and multiple invoices. It recognizes compact IBAN-like tokens (including Unicode letter/digit prefixes without repairing them), complete GB/DE grouping patterns, and explicit IBAN/account/routing/sort-code/wallet label regions. It retains the literal raw string, source ID, exact character range, surrounding source context and an optional checksum-valid GB/DE identity. Leading zeros and full identifiers remain significant. Only the existing safe ASCII space/case equivalences deduplicate account identities; separate routing remains literal. Sentence punctuation and standalone scheme labels are not invented competing accounts.

This inventory is **not AI extraction** and is never merged into an AI-attributed observation. The original `PaymentRequestEvidence`, method, candidates and evidence spans remain untouched. Missing stays missing. Inventory entries are lexical review signals, not claims that a bank account exists, belongs to someone, is payable, or represents the current instruction. An omitted value is visible as `NOT OBSERVED BY EXTRACTION`, with its own exact source context. The normal evidence/source contract still rejects fabricated quotes and incomplete account-token substrings.

The inventory has at most 256 observations. Overflow explicitly blocks a decisive result, rather than silently discarding later instructions. Sources remain bounded by existing contracts. Each entry preserves 160 characters of surrounding context on either side, and the interface also displays **the full original sources**. Display uses JSON escaping for controls/Unicode; source text cannot inject an authoritative VERIFIED terminal line.

Local wording may produce `HISTORICAL_WORDING`, `CURRENT_WORDING`, `QUOTED_CONTEXT` or `UNKNOWN` **hints**. These describe nearby literal wording, not proven relevance or intent. Even clearly historical wording does not authorize automatic removal of a different destination. Model confidence, a legitimate explanation, document ordering or a blanket acknowledgement cannot suppress an inventory candidate. The inventory receives neither the trusted baseline nor model confidence/role decisions.

## Eligibility gate

The existing field-based engine already fails closed on missing, invalid, unsupported or competing extracted destinations. The new gate adds independent checks where the extracted observations could otherwise resolve to **one complete supported identity**:

- More than one distinct destination-like account region across the source bundle blocks with `UNCERTAIN / DESTINATION_AMBIGUOUS`, including a real current IBAN omitted by extraction.
- Unaccounted-for explicit destination regions, reference-only historical/quoted observations, no independently recognized account, or inventory overflow block with `UNCERTAIN / DESTINATION_INCOMPLETE` when no ambiguity blocker takes precedence.
- Equivalent repeated representations of the same full supported account can still match after existing source review. Repetition never increases confidence, and inventory overflow is not exempted even if early entries all match.
- Invalid/missing/ambiguous extracted identities keep their existing fail-closed reasons; the guard does not reinterpret or repair them to improve utility.

The comparison includes a source-completeness missing-information explanation. It does not manufacture AI evidence IDs for an omitted observation. Source IDs/offsets/context are exposed separately by the inventory and remain recomputable from the immutable case sources.

The pure comparator always applies this check. `CaseContract` also rejects a decisive stored/forged result when its source instructions are unresolved, so callers cannot bypass the check by constructing a result or displaying an old-style match. Source review still records an explicit acknowledgement, but **that boolean does not clear this independent gate**. Neither scanner nor model can create VERIFIED or independent verification.

## Intentional utility cost and resolution

A document containing an explicitly retired account plus a different current account now remains UNCERTAIN, even with otherwise perfect extraction. An account-shaped purchase-order code can also cause conservative abstention. Those are retained benchmark failures against its original desired VERIFY labels, not relabeled successes or claimed extraction improvements. No automatic source-role exclusion, special-case vendor rule or benchmark-ID exception exists.

Phase 1 has no fine-grained role-resolution/exclusion action. Resolve the conflicting source bundle outside this prototype through independently checked vendor instructions; do not delete inconvenient text, promote a cleaned transcription into trusted evidence, or override this gate to obtain a favorable state. A future scoped human resolution contract would need exact source occurrences, preserved original candidates, explicit supported dispositions, operator/time/provenance and fresh comparison. AI confidence must never substitute for that action. This task does not implement that feature.

## Remaining limitations

This is a lexical tripwire, **not exhaustive discovery or proof of current payment intent**. Obfuscated, badly corrupted, image-only, unlabeled local/wallet/payment-link or fragmented destinations can evade it. Arbitrary prose roles, source authenticity and unseen attachments remain unresolved. A false human acknowledgement on an undetected wrong-role single value is still possible. No claim that all dangerous misses are eliminated is justified.

Current/historical wording hints are deliberately non-authoritative and can be wrong or manipulated. Account-shaped irrelevant data causes unnecessary abstention. Long bundles may exceed the inventory cap. Full-source review and independent vendor verification remain necessary; lack of a scanner warning is not evidence of unchanged instructions. Without a complete extracted destination and explicit review, existing comparison gates still prevent UNCHANGED.

## Actual diagnostic benchmark rerun

Original frozen Phase-1 labels and corpus SHA-256 remain unchanged. These are **gold-observation deterministic runs with simulated source review**, not live extraction results or held-out model accuracy.

| Metric | BEFORE | AFTER |
| --- | --- | --- |
| Cases | 30 | 30 |
| Correct state / exact result | 30/30 | 28/30 |
| Known consequential changes | 13 | 13 |
| Source-correct VERIFY detections | 10 | 8 |
| Changes not detected as correct VERIFY | 3 | 5 |
| Changed cases abstained | 3 | 5 |
| Critical false UNCHANGED | 0 | 0 |
| False VERIFY on known unchanged | 0 | 0 |
| Expected uncertain handled correctly | 13/13 | 13/13 |
| Gold comparison mismatches | 0 | 2 |
| Unreviewed gate correct states | 30/30 | 30/30 |
| Unreviewed exact reasons/results | 30/30 | 28/30 |
| Extraction/provider evaluation | NOT_RUN | NOT_RUN |

AFTER remains **FAIL** against the existing corpus's desired utility: PP-09 (historical IBAN plus current IBAN) and PP-12 (account-shaped lookup code plus current IBAN) yield UNCERTAIN instead of VERIFY. This is a conservative source-resolution cost, not a normalization repair, label change or provider failure. The stronger gate exposes it honestly. The initial implementation's punctuation/label defects were fixed generally; they are not accepted extra benchmark failures.

**Verification:** Ruff lint/format, strict mypy, all **658 tests** (including 20 new source-instruction regressions), production wheel/source build and installed-package/console/production-WSGI smoke pass. The 72 held-out definitions still validate without predictor execution. Live readiness is false in the current process environment; no provider request or live model accuracy claim was made. `make verify` currently stops at the benchmark’s intentional utility FAIL; the other checks were run separately.

Actual retained artifacts:

- `benchmarks/instruction-safety/before/report.json` and `summary.txt`: pre-change run.
- `benchmarks/instruction-safety/intermediate/`: first implementation, including the subsequently fixed extra reason on PP-30; preserved rather than overwritten.
- `benchmarks/instruction-safety/after/report.json` and `summary.txt`: final rerun.

To reproduce:

```bash
.venv/bin/python -m pytest -q tests/test_instruction_safety.py tests/test_redteam.py
.venv/bin/python -m payproof benchmark --output /tmp/payproof-instruction-safety-new-run
```

The benchmark command intentionally exits 1 for the two unchanged-label utility mismatches. Do not weaken its acceptance criteria or change labels to get exit 0. The separate held-out definitions remain frozen. Live model performance remains unmeasured; absent environment configuration is not replaced with a fixture or mock accuracy claim.
