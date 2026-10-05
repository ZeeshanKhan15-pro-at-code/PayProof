# Deterministic normalization and comparison

Implemented in [normalization.py](../payproof/normalization.py) and [comparison.py](../payproof/comparison.py), under rule version `iban-gb-de-v1`. The engine uses no model, provider, I/O, clock, randomness, fuzzy matching, or fraud score. It preserves the [frozen Phase-1 scope](ARCHITECTURE.md#deterministic-comparison-contract): one manually selected trusted vendor revision and GB/DE IBAN destinations.

## Calling contract

```python
from payproof.comparison import compare

result = compare(
    case,  # validated CaseContract with sources/evidence/baseline/review
    comparison_id=comparison_id,  # UUID supplied by the application
    compared_at=compared_at,  # authoritative aware UTC datetime from the application
)
```

When `case.baseline` is absent, supply `selected_vendor_id` explicitly; the engine never invents a vendor or baseline. A supplied vendor ID must match an existing baseline. The caller supplies server IDs/times so identical snapshots and metadata yield identical results. The caller must authenticate the human review; a Pydantic object alone does not prove human participation.

The engine revalidates the whole case, including nested objects, source digests, exact quotes/offsets, provenance chronology, extraction attribution, and review bindings. It validates the produced result against the same source-bound contract before returning it. Malformed envelopes, invalid metadata/chronology, and unchecked invalid `model_copy`/`model_construct` objects raise validation errors and produce no decision. The application must display a failed operation as unresolved; it must never reuse an earlier decisive result as a fallback. A validated extraction failure, including rejected provider evidence, produces `UNCERTAIN` with the corresponding failure reason.

Pass a fresh snapshot with no prior comparison or verification. Comparing again requires a new snapshot and new authoritative result metadata; existing history must be preserved by the later persistence layer. The comparator does not create a source review, independent-verification record, or payment approval.

## Normalization rules

| Representation | Deterministic rule | Deliberately preserved/rejected |
| --- | --- | --- |
| IBAN account identifier | Remove only ASCII U+0020 spaces; uppercase ASCII letters; check country layout and MOD-97 | Reject dashes, punctuation, tabs/newlines, Unicode characters/lookalikes, masked/truncated values, invalid checksums, unsupported countries; preserve every digit and leading zero |
| GB IBAN | Exactly 22 canonical characters: `GB`, two check digits, four ASCII bank letters, fourteen digits | No edit-distance repair, suffix comparison, bank alias lookup, or digit/letter substitution |
| DE IBAN | Exactly 22 canonical characters: `DE`, twenty digits | Bank/routing digits encoded inside the IBAN participate in complete identifier equality |
| Scheme label | Strip surrounding ASCII spaces and uppercase ASCII letters | Only `IBAN` is supported; no mapping from ACH, SWIFT, local-account labels, or Unicode spellings |
| Separate routing identifier | Bounded nonblank text without ASCII controls, returned unchanged | No separator removal, case conversion, zero removal, or numeric conversion without a supported routing scheme |
| Domain | Trim surrounding ASCII space/tab/CR/LF; validate narrow ASCII DNS labels and lowercase | Reject Unicode conversion, URL syntax, repeated dots and trailing dots; preserve hyphens and subdomains |
| Email | Trim surrounding ASCII whitespace; validate narrow ASCII dot-atom address; lowercase domain only | Preserve local-part casing, dots and plus tags; reject display names and internal whitespace |
| Currency | Trim surrounding ASCII whitespace; uppercase exactly three ASCII letters | Reject ambiguous symbols such as `$`, aliases and Unicode; checks representation, not membership in a currency registry |
| Vendor-name display | Collapse ASCII space/tab/CR/LF; trim ASCII spaces | Preserve case, punctuation, legal suffixes, accents and Unicode; never use this to select/match a vendor |

Raw account input is limited to 256 characters. Empty, explicit masked (`*`) or ellipsis-marked accounts, and supported-country accounts shorter than 22 characters are incomplete. Other malformed characters/layouts/checksums are invalid. Unsupported country prefixes are unsupported; they are never converted to GB/DE. No normalization validates ownership or payment safety.

Only the complete canonical IBAN establishes supported destination equality. Context helpers are available for display; comparison differences preserve raw contextual observations to retain exact evidence binding. Name/email/currency/bank-label formatting or changes do not alter the destination state.

## Exact state derivation

All applicable uncertainty blockers are collected and deduplicated in the stable order below. The first code identifies the earliest failed gate. Any blocker yields `UNCERTAIN`, even if a valid observed account happens to match the baseline. There is no partial `VERIFY` result when another consequential instruction remains unresolved.

| Ordered gate | Machine-readable reasons | Derivation |
| --- | --- | --- |
| 1. Trusted baseline | `BASELINE_UNAVAILABLE`, `BASELINE_INVALID` | An absent baseline emits `BASELINE_UNAVAILABLE`. Invalid baseline contracts are rejected at validation; `BASELINE_INVALID` remains reserved for a future validated load-failure record, and is not fabricated by this engine. |
| 2. Extraction/evidence | `EXTRACTION_FAILED`, `EVIDENCE_INVALID` | `EVIDENCE_INVALID` extraction failure emits that code. Other explicit failures, including `NOT_CONFIGURED`, emit `EXTRACTION_FAILED`. Arbitrarily corrupted source/evidence objects are rejected before a result exists. |
| 3. Source review | `REVIEW_REQUIRED` | With successful extraction, no review, no reviewed identity for a valid unique account, or omitted consequential account/scheme/routing spans means incomplete review. A failed extraction already supplies its failure reason. |
| 4. Destination completeness | `DESTINATION_MISSING`, `DESTINATION_INCOMPLETE` | Missing account emits `DESTINATION_MISSING`. Unreadable account/scheme/routing fields, masked accounts or truncated supported accounts emit `DESTINATION_INCOMPLETE`. An omitted scheme label is permitted when the complete identifier itself validates as a supported IBAN. |
| 5. Supported format and validity | `UNSUPPORTED_DESTINATION`, `DESTINATION_INVALID` | Unsupported extraction category/country/scheme, any observed separate routing instructions, or raw separate routing in the baseline emits `UNSUPPORTED_DESTINATION`. Invalid IBAN characters/layout/checksum emits `DESTINATION_INVALID`. An unreadable routing field emits incomplete, without claiming an observed unsupported route. |
| 6. Unresolved destination observations | `DESTINATION_AMBIGUOUS` | Multiple account observations that cannot all normalize to one supported valid IBAN, unresolved multiple scheme observations, or distinct raw routing observations emit ambiguity and a contradiction with all relevant evidence IDs. A mixture of valid and invalid accounts remains unresolved. |
| 7. Complete reviewed equality | `DESTINATION_MATCH` | If no blocker exists and the unique canonical requested IBAN equals the frozen canonical trusted IBAN, return `UNCHANGED` with this singleton reason. |
| 8. Complete reviewed change | `DESTINATION_CHANGED` | If no blocker exists and the canonical IBANs differ, return `VERIFY` with this singleton reason. A changed bank/routing portion inside an IBAN counts as a change. |

An extraction field marked `AMBIGUOUS` retains all original candidates/spans. Repeated observations may become decisive only if **every** account observation is valid and resolves to the same canonical IBAN, the human reviewed every corresponding span, and the review's raw identity exactly matches one of those observations. Repeated scheme labels must all normalize to `IBAN` and all be reviewed. This narrowly resolves the original schema/architecture mismatch about duplicate mentions; it permits no selection among genuinely different destinations. Resolve distinct instructions in a new supported source/extraction/review snapshot.

Separate routing instructions are outside the frozen Phase-1 identity contract. Even an exact raw routing match returns `UNCERTAIN`; a raw routing difference is displayed as `CHANGED`, but cannot independently produce `VERIFY` until a scheme-specific comparison contract is implemented in Phase 2/3. The engine never silently ignores those instructions. Other destination schemes likewise require a later explicit contract and tests.

`UNCHANGED` reports complete supported destination equality. `VERIFY` reports changed instructions requiring independent human verification; a legitimate vendor update may cause it. `UNCERTAIN` reports inability to compare safely. The engine never returns `FRAUD`, `LEGITIMATE`, `SAFE`, `SAFE TO PAY`, or `VERIFIED`.

## Result and evidence

Every result binds the request, selected vendor, baseline revision, review, rule version, server comparison ID/time, and exact identity snapshots. Requested identity is copied only from a valid human review; an unreviewed observation can populate a source-backed account difference but cannot become a reviewed identity or decisive state.

Account differences use a valid unique canonical value, or `null` when it cannot be resolved. Raw observations remain in evidence. Differences also cover vendor name, sender email, bank label, currency, separate routing and explicit scheme. Contextual values remain raw; absent/ambiguous values yield `UNKNOWN`. Destination absence/unreadability is listed under `missing_information`. Contextual contradictions are recorded without blocking a supported destination decision. All differences/contradictions cite field-specific existing spans; a contradiction retains at least two references. The full result declares the extraction's evidence IDs, retaining access to invoice/amount/reply-to/change-claim/reason observations even when no trusted counterpart exists.

A quote proves only that text exists in the immutable source. The human must review whether all current destination instructions were extracted and distinguish historical, hypothetical or canceled instructions. The engine cannot detect a consequential instruction that extraction omitted.

## Tests and benchmark

Run the complete offline gate:

```bash
make verify
```

[Normalization tests](../tests/test_normalization.py) cover grouping/case, rejected punctuation/Unicode/masking/checksums, conservative contextual formatting and routing preservation. [Comparison tests](../tests/test_comparison.py) cover all states and blockers, duplicate/conflicting accounts and schemes, cross-document contradictions, complete human review, rejected malformed/copy-bypassed contracts, input immutability, repeated deterministic output and forbidden provider/I/O calls. Generated valid nearby GB accounts share suffixes while differing in their full destinations; DE cases change embedded bank/routing digits. The existing schema/extraction suite remains a regression gate.

`make benchmark` runs the frozen 30-case [benchmark specification](BENCHMARK_SPEC.md), scoring state, ordered reasons, complete values, missing/conflicting information and evidence, with explicitly simulated source reviews and a separate unreviewed gate. It writes JSON and a readable summary and fails on any incorrect case. `make benchmark-extraction` adds source-only configured extraction and a conditional pipeline without human corrections; replay re-scores the saved observations without provider calls. Failures remain in denominators and identify the exact case and extraction/comparison stage. The older ten-fixture runner remains available as `python -m payproof benchmark-fixtures`.

Measured diagnostic results are stored under [results](../benchmarks/phase1-v1/results/README.md). They create no human verification events and do not establish live AI accuracy when extraction is disabled. Independent label review and the architecture's 36-case release corpus/held-out runs remain incomplete. Development regression agreement does not establish real-world fraud-detection performance.
