# Phase-1 red-team report

Reviewed the architecture, canonical schemas, benchmark specification and recorded results, provider/extraction pipeline, normalization/comparison, source provenance, display and configuration code. The architecture, supported destinations, normalization policy, benchmark cases and expected states are unchanged. No verification command, OCR, database, authentication flow or unrelated product feature was added.

## Method and actual outcomes

Added [regression tests](../tests/test_redteam.py) **before fixes**. The first run produced **24 failures and 36 passes across 60 checks**. Follow-up lexical attacks then reproduced **seven additional failures** (with ten earlier fragment checks passing), before tightening that same boundary. Provider responses are deliberately injected; tests forbid real network calls. These checks measure handling of malicious responses, not how frequently a live model produces them. The final suite retains all attack variants and additional guard checks, without skips or expected-failure markers.

Final validation: **73/73 red-team checks and 588/588 full-suite tests pass**. Ruff lint/format checks, strict typecheck and production build (including wheel smoke validation) pass. The original [initial failing run](../benchmarks/phase1-v1/results/redteam-before/tests.txt) and [follow-up failing run](../benchmarks/phase1-v1/results/redteam-before/token-followup-tests.txt) are preserved. Configured-extraction replay reproduces the identical scoring digest and tracks, with the expected nonzero exit for disabled extraction.

Reran the entire 30-case benchmark. Original reports are retained under [redteam-before](../benchmarks/phase1-v1/results/redteam-before/gold/summary.txt); updated [gold](../benchmarks/phase1-v1/results/gold/summary.txt) and [extraction](../benchmarks/phase1-v1/results/extraction/summary.txt) reports record the new runs. [redteam-comparison.json](../benchmarks/phase1-v1/results/redteam-comparison.json) contains measured before/after counts and digests. Corpus SHA-256 remains `3bc6dcafaeb661b00cf22fd06fc86802c8db642c41d9228676faae3b546a0c7f`.

## Attacks attempted

| Category | Attacks | Observed handling after fixes |
| --- | --- | --- |
| Extraction | Irrelevant invoice/amount/extension numbers; sender/reply-to mismatch | Source-backed destination drives comparison; reply-to remains context and never becomes the trusted callback |
| Extraction / comparison | Multiple accounts, footer account versus invoice body, contradictory email/invoice, reversed candidate order | Distinct observed candidates remain `UNCERTAIN / DESTINATION_AMBIGUOUS`; no winner selected |
| Extraction / provenance | Duplicate invoice sections, identical documents with different IDs, repeated excerpt without unique context | Equivalent accounts can match after review; source bindings retained; nonunique excerpt alone rejected |
| Extraction / state machine | Historical account in explanatory prose with current account omitted | Unreviewed input stays uncertain; incorrect acknowledgement can still cause a false match—residual risk below |
| Extraction / reliability | Duplicate account property, nested value/status, provider output/status, canonical JSON key | Whole ambiguous JSON rejected; no silent last-value-wins interpretation |
| Provenance | Checksum-valid IBAN quoted as a prefix/infix of a longer identifier; clipped excerpts | Partial-token evidence rejected rather than normalized as a complete account |
| Normalization | Leading zeros, account-tail collisions, spaces, case, dashes, tabs, punctuation, NBSP, fullwidth/Cyrillic text, combining/zero-width characters, OCR O/0 corruption | Full identity preserved; no suffix comparison, zero removal, Unicode conversion or character repair |
| State machine / provenance | Old UNCHANGED comparison copied into changed case; forged VERIFIED enum; corrupt source digest | Complete snapshot revalidated before evidence/result display |
| State machine | AI verdict, fabricated human confirmation/operator, legitimate-sounding claims, newline/terminal-control status spoofing | Extra model fields rejected; quoted source claims remain data; no authoritative VERIFIED status or verification event |
| Reliability | Timeout, empty/malformed/deep output, schema failure, long input, duplicate document IDs, missing account/source | Failed extraction cannot receive successful review; invalid inputs fail closed; no approval fallback |
| Reliability / configuration | Canonical source/candidate floods; nonempty example secret | Existing source/candidate limits enforced throughout; example secret cleared |

Existing HTTP/envelope failure, source chronology, schema, review-binding, normalization, comparison and benchmark regressions were also rerun. Live adversarial-model trials were not performed: process extraction remains disabled, with no configured provider key/model. `.env.example` is not automatically loaded.

## Failures found and fixes made

### RT-01 — Duplicate JSON could erase earlier evidence

**Categories: extraction, reliability, provenance. Six initially failing checks.**

The JSON parser accepted duplicate object keys and kept the last value. A response could contain a new account followed by a source-quoted old account, or overwrite an incomplete provider envelope with a completed one. Schema-constrained shape did not prevent this ambiguity.

[validation.py](../payproof/validation.py) now rejects duplicate keys recursively before Pydantic parsing. It also rejects nonfinite JSON constants and sanitizes invalid encoding/excessive decoder nesting. Provider envelopes, model payloads, canonical input parsing, bundled fixtures, and benchmark corpus/replay input use this boundary. Model/envelope failures become `INVALID_RESPONSE` with unreadable fields. No account is selected to salvage malformed JSON.

### RT-02 — Valid account fragment could masquerade as a complete account

**Categories: extraction, provenance. Eleven initially failing checks, plus seven failing follow-up variants.**

An excerpt could select a checksum-valid trusted IBAN from a longer malformed identifier, such as the trusted value followed by additional digits. Normalization accepted the shortened value, potentially yielding `UNCHANGED` after acknowledgement. Exact substring presence did not establish completeness.

Added shared lexical grounding in [provenance.py](../payproof/provenance.py), enforced by live extraction and `CaseContract`, including manual/cached evidence. It examines original source characters outside clipped excerpts. Adjacent letters/digits, combining/format characters, Unicode connectors/dashes/math symbols, masking/ellipsis markers, dotted continuations and following numeric groups separated by horizontal whitespace invalidate the fragment. Follow-up tests specifically reproduced dot suffixes, Unicode dashes/minus/connectors, tab, NBSP and thin-space suffixes before the shared check was tightened. Outer ASCII spaces cannot hide attached continuations. Every occurrence of the value inside its excerpt must pass.

Complete malformed raw values remain representable so existing normalization can return `UNCERTAIN`. Ordinary sentence punctuation/delimiters remain supported. This establishes lexical completeness only; it does not discover omitted instructions or establish their current-payment role.

### RT-03 — Display trusted unchecked/copied snapshots

**Categories: state machine, provenance, reliability. Three initially failing checks.**

The comparator revalidated snapshots but presentation did not. A copied case could display an old `UNCHANGED` comparison alongside changed sources/review. An unchecked `VERIFIED` enum raised `KeyError`; it did not create a human verification record.

Both [presentation.py](../payproof/presentation.py) entry points now reconstruct and validate the whole case before output. Stale destination/revision bindings, corrupt sources, fabricated nested objects and illegal states fail before display. Original text remains escaped evidence: a literal quoted word `VERIFIED` is not an authoritative status.

### RT-04 — Canonical limits were weaker than adapter limits

**Category: reliability. Three initially failing checks.**

The adapter already limited sources/candidates, but canonical records admitted more than 16 sources, 16 candidates per field, or 64 overall. Manual/replayed callers could bypass those bounds.

Enforced the same limits in [schemas.py](../payproof/schemas.py), including source ID lists, and refreshed the exported diagnostic JSON Schema. No fields or allowed states were added. Source text remains bounded to 20,000 characters; the cross-field total-candidate rule additionally requires Pydantic validation.

### RT-05 — Tracked configuration example contained a credential-like value

**Category: configuration/security hygiene. One initially failing check.**

Cleared the nonempty provider-key placeholder in `.env.example` and added a regression check that provider/signing secrets in the example stay empty. The public model-name setting was preserved. No key was copied into `.env`, used in an API call, or written into test/benchmark artifacts; this report does not reproduce it.

**Remaining operational action:** if that value is live, its owner must revoke/rotate it. Clearing the working file does not remove the value from Git history or prove revocation. No destructive history rewrite or external credential-management action was performed.

## Most important invariant

Attempted model verdicts and human impersonation were rejected. Illegal comparison states are rejected before display. No tested application path created a verification record or authoritative `VERIFIED` status solely from AI output. Comparison states remain `UNCHANGED`, `VERIFY`, and `UNCERTAIN`.

Independent human verification is still an unimplemented command boundary. A structurally valid human record cannot authenticate a person or prove a callback happened. This exercise does not certify a future verification/web implementation.

## Remaining weaknesses

- **Historical-role/omission false matches remain reproducible.** Extraction can correctly quote a historical/trusted account while omitting a distinct current account. Unreviewed input produces `UNCERTAIN / REVIEW_REQUIRED`; a false human acknowledgement can still produce `UNCHANGED`. The retained regression explicitly demonstrates this residual risk. Schema, checksums and lexical grounding cannot prove relevance/completeness. No document-wide regex, fraud classifier or automatic role approval was added.
- An omitted footer or contradictory instruction has the same limitation. Ambiguity protection works when candidates are retained; it cannot compare evidence it never received.
- Contextual sender/reply-to/name/bank-display values do not authenticate the sender or select state. The previously trusted callback remains the independent-check channel.
- Lexical checks are conservative: adjacent footnote markers or undelimited numeric columns may require a better-delimited source/excerpt. Distant or line-wrapped omissions are not universally detectable. This is not OCR or a complete payment-instruction parser.
- Live model accuracy is unmeasured. Tested socket timeouts and size bounds do not establish a complete wall-clock deadline for every slow provider behavior.
- Persistence, authenticated source-review identity, current-revision enforcement across requests and independent verification remain later targets. Web endpoints are read-only. CLI operator labels cannot prove honest participation.
- Independent label review remains `PENDING`; public diagnostic cases do not replace the 36-case release corpus/held-out evaluation. Passing regressions does not establish population reliability or fraud-detection performance.
- The old example value remains in Git history pending owner action.

## Benchmark change before / after

| Gold-comparison metric | Before | After |
| --- | --- | --- |
| Total cases | 30 | 30 |
| Correct states | 30/30 | 30/30 |
| Exact state/reason/value/evidence agreement | 30/30 | 30/30 |
| Known consequential changes | 13 | 13 |
| Correct VERIFY detections | 10 | 10 |
| Changes not detected as VERIFY | 3 | 3 |
| Supported changes detected | 10/10 | 10/10 |
| Changed cases abstained | 3 | 3 |
| Critical false UNCHANGED | 0 | 0 |
| Unchanged incorrectly escalated | 0 | 0 |
| Expected uncertainty handled correctly | 13/13 | 13/13 |
| Comparison failures | 0 | 0 |
| Unreviewed gold gate agreement | 30/30 | 30/30 |

PP-07, PP-08 and PP-29 remain unsupported-change abstentions, not detections. The 30-case corpus did not exercise the new boundary defects; unchanged aggregate results do not invalidate the attack reproductions.

Configured extraction before/after records **30 `NOT_CONFIGURED` failures**, **0/30 successful classifications**, **0 detections**, and **0 comparison failures**. It remains a failed extraction evaluation. Its two tracks share the same attempts, not 60 independent attempts. Scoring counts/digests are unchanged; code hashes identify the fixes. No expected labels, source fixtures, or normalization policy were adjusted to improve results.

## Reproduction

```bash
make lint typecheck test
make benchmark
make benchmark-extraction
make build
.venv/bin/python -m payproof benchmark --replay benchmarks/phase1-v1/results/extraction/report.json
```

The configured-extraction command and replay remain nonzero until a usable provider and passing observations are available; failures are recorded rather than substituted with fixtures. The attack regressions and residual-risk reproduction are in `tests/test_redteam.py`.
