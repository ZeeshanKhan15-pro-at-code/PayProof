# PayProof architecture

Status: Phase-1 architecture frozen. This document is a build contract, not an implemented system.

## Scope and repository inspection

PayProof helps a business notice that a requested payment destination differs from a previously trusted vendor destination and require independent human verification. It does not decide whether to pay or whether fraud occurred.

At inspection, the workspace contained no application source, dependency manifest, existing documentation, or usable Git repository. There is no existing implementation to preserve. No application features are implemented by this architecture task.

The three-day target is one operator, one deployment, manually selected vendors, pasted text, and IBAN destinations. Every comparison is scoped to a specific trusted vendor baseline revision. No automatic vendor matching is permitted.

## Safety invariants and product language

- The comparison engine returns exactly `UNCHANGED`, `VERIFY`, or `UNCERTAIN`.
- `UNCHANGED` means only that the reviewed, supported payment destination matches the selected trusted baseline. It does not authorize payment or establish document authenticity.
- `VERIFY` means that a complete, supported destination differs from the trusted baseline. A change requires independent human verification; it does not establish fraud.
- `UNCERTAIN` means that the system cannot make a reliable comparison. It requires human resolution and then a new comparison.
- AI cannot return or persist a decision, set baseline trust, select the vendor, or create `VERIFIED`.
- Only the explicit human verification command may create `VERIFIED`, scoped to the exact reviewed destination and comparison. Verification is a record of a person's attestation, not proof that the payment is safe.
- Store comparison state separately from human verification. Verification never overwrites a historical `VERIFY` or `UNCERTAIN` result.
- No state triggers payment, approval, accounting updates, or automatic baseline replacement. Avoid “safe,” “fraud score,” and green payment-approval language in the UI.

## Components and technology

One Python application serves server-rendered HTML and a few form/JSON endpoints. Use Flask, Gunicorn for hosting, SQLite through Python's standard library, and pytest for development. Use standard-library HTTP for one extraction provider adapter, with bounded requests and timeouts. Pin dependencies when implementation begins. Do not add an ORM, frontend framework, agent framework, vector store, or background worker.

SQLite is justified by persistent baseline revisions, cases, and human attestations across restarts. It is not an accounting database. Run one application instance with a persistent local volume; do not use multiple replicas or a shared network filesystem. Synchronous extraction is sufficient for bounded pasted text and a hackathon workload.

```text
                         OPERATOR / HUMAN
                      trusted onboarding information
                      previously trusted contact channel
                                  |
                                  v
 +---------------------- browser / private access ----------------------+
 | Paste request text -> review extracted fields -> view comparison     |
 | Select vendor       -> inspect quoted evidence -> attest verification|
 +-------------------------------+--------------------------------------+
                                 | same-origin forms / JSON
                                 v
 +----------------------- ONE PYTHON SERVICE ---------------------------+
 | web: input limits, CSRF, escaped rendering, operator session          |
 |                                                                     |
 | cases -> extraction adapter ------ external AI API                   |
 |           |                     (untrusted, no tools or state access)|
 |           v                                                         |
 |       schema + exact evidence validation -> human source review      |
 |           |                                                         |
 |           v                                                         |
 | baseline revision ------> pure deterministic comparator             |
 |                                    |                                |
 |                          UNCHANGED / VERIFY / UNCERTAIN              |
 |                                    |                                |
 | human independent-verification command -> scoped VERIFIED event      |
 |                                                                     |
 | persistence: transactions, immutable snapshots, audit events         |
 +-------------------------------+--------------------------------------+
                                 |
                                 v
              SQLite + persistent local disk (private data)
```

### Module responsibilities

These are small modules within one process, not independently deployed services.

| Module | Responsibility | Forbidden responsibility |
| --- | --- | --- |
| `web.py` and templates | Forms, input bounds, CSRF, operator identity, escaped evidence, status explanations | Inventing decisions or trusting posted state fields |
| `cases.py` | Case lifecycle, source review, snapshot selection, orchestration | Destination comparison rules |
| `extraction.py` | One provider call or explicitly labeled fixture mode; strict parse and evidence validation | Trust, identity resolution, payment advice, persistence privileges |
| `comparison.py` | Pure validation, normalization, equality, reason codes | AI calls, storage, verification, fuzzy matching |
| `verification.py` | Validate explicit human attestations and bind them to a comparison | Updating the baseline or accepting AI verification |
| `storage.py` | SQLite schema, immutable records, parameterized queries, atomic writes | Hidden decision logic |
| `fixtures/` and `tests/` | Synthetic sources, trusted baseline examples, expected extraction and comparison outcomes | Real financial or customer data |

## Data contracts and provenance

Use application-generated identifiers and server timestamps. Store UTC timestamps and show a clear timezone in the UI. Keep original text immutable; edits create a new case or revision.

Minimum persistent records:

1. **Vendor and baseline revision:** vendor ID, operator-entered display name, destination scheme, raw and canonical IBAN, currency if supplied, revision ID, creating operator and time, trust-origin description, and a previously trusted contact channel with its provenance. Phase 1 supports one destination per vendor. A request under review cannot establish its own baseline or trusted contact. Baseline entry is a human trust assertion, never AI inference.
2. **Case:** selected vendor ID, original pasted UTF-8 source, source ID, SHA-256 digest, operator and time, and captured baseline revision ID. Filename/email title is an optional human label and is never identity evidence.
3. **Extraction attempt:** provider/model identifier as reported or configured, prompt/schema version, attempt time, input source digest, validated candidate fields, and sanitized failure code. Each destination candidate has raw text, character offsets, exact source quote, scheme, and ambiguity flags. Preserve the structured provider response privately for audit; never persist authorization headers or provider credentials.
4. **Source review:** operator, time, reviewed candidate selection or correction, exact source span, and explicit acknowledgement that the supported destination instructions were checked. Corrections are append-only and retain the original extraction attempt. A manually entered value without matching source evidence cannot support `UNCHANGED`.
5. **Comparison:** immutable comparison ID, case/review ID, baseline revision ID, raw and normalized compared values, rule version, result, and machine-readable reasons. A missing value is stored as missing, never as a fabricated empty destination.
6. **Verification event:** comparison ID, exact destination snapshot, baseline/contact revision, operator identity, server time, method, trusted contact reference, independently reached person/role, and an attestation that the exact destination was confirmed through that channel. Include a brief verification note; do not require call recordings or new document uploads.

Record baseline creation, source review, comparison creation, and verification as append-only application events. SQLite access by the host administrator can alter records; do not claim cryptographic tamper resistance. A digest binds an internal source snapshot; it does not authenticate its sender or content.

## Data flow

1. The operator creates a baseline from information trusted before the current request, or selects a synthetic seeded baseline. Record how it became trusted and the independent contact to use later.
2. The operator selects that vendor and pastes a payment request/email/invoice excerpt. Accept at most 20,000 Unicode characters, with an explicit HTTP body-size limit. Freeze the source and baseline revision.
3. The service calls the extractor synchronously. Source text is untrusted data within the extraction prompt. The provider has no tools, database access, or ability to call application commands.
4. Validate the response against an allowlisted schema and validate every quote/offset against the immutable source. Reject unexpected fields, including decision fields. Missing, conflicting, unsupported, or invalid output produces `UNCERTAIN` with reasons, not a guessed comparison. A subsequent manual extraction is a new, explicitly attributed attempt with the same evidence validation; an earlier provider failure remains in history but does not invalidate that new attempt.
5. Show the original source alongside proposed fields. The operator reviews the supported destination instructions and confirms or corrects extraction with a source span. Source review establishes what to compare; it is separate from independent verification. Before review, valid extraction remains pending; pending is a workflow stage, not a fourth product decision.
6. Compare the reviewed candidate with the frozen baseline. Persist the result and evidence together, then show the result, reason, old/new destination, quotes, and baseline provenance.
7. For `VERIFY`, require verification through the previously trusted channel. Provide an explicit attestation form with no preselected checkbox. The server validates the attestation and writes a verification event atomically. `UNCHANGED` may also be independently verified if the operator chooses.
8. For `UNCERTAIN`, resolve the missing/ambiguous information and create a fresh source review and comparison first. Phase 1 does not let a verification form bypass an unresolved destination.

The case view shows both the original comparison and, if present, “VERIFIED by [operator] via [method] at [time] for [destination].” The verification display is derived from a valid stored event, never from a submitted status string.

## Deterministic comparison contract

Inputs are the reviewed candidate, immutable baseline revision, and their validity/evidence metadata. Outputs are a result and reason codes. The function performs no I/O.

Phase 1 supports IBAN only. Validate both values using format, a pinned country-length table for the explicitly supported countries, and the MOD-97 checksum. Support GB and DE synthetic fixtures initially; other countries are `UNCERTAIN` until explicitly supported and tested. A valid checksum does not establish account ownership or bank authenticity.

Normalization removes ASCII spaces and uppercases ASCII letters. Preserve the raw values. Do not strip punctuation, silently convert Unicode characters, repair digits, perform edit-distance matching, or compare account suffixes. Unexpected characters are invalid. Grouping spaces and ASCII case may differ without changing the destination.

Evaluate in this order:

| Condition | Result / reason |
| --- | --- |
| No selected trusted baseline, missing trust/contact provenance, or invalid baseline | `UNCERTAIN / BASELINE_UNAVAILABLE` or `BASELINE_INVALID` |
| Extraction failed, evidence failed, or source review is incomplete | `UNCERTAIN / EXTRACTION_FAILED`, `EVIDENCE_INVALID`, or `REVIEW_REQUIRED` |
| No complete destination, truncated/masked account, unsupported scheme/country, or invalid characters/checksum | `UNCERTAIN / DESTINATION_MISSING`, `DESTINATION_INCOMPLETE`, `UNSUPPORTED_DESTINATION`, or `DESTINATION_INVALID` |
| Multiple distinct destinations or contradictory instructions remain unresolved | `UNCERTAIN / DESTINATION_AMBIGUOUS` |
| Exactly one supported valid reviewed destination equals canonical baseline | `UNCHANGED / DESTINATION_MATCH` |
| Exactly one supported valid reviewed destination differs from canonical baseline | `VERIFY / DESTINATION_CHANGED` |

Repeated mentions of the same canonical destination are not conflicting. An operator cannot choose one of conflicting destinations and discard the others without resolving the instructions with supporting evidence in a new source snapshot. If the extractor misses an instruction, source review is the remaining control; PayProof does not guarantee complete extraction of arbitrary documents.

Vendor names, invoice amounts, sender domains, writing style, and model confidence cannot change the decision. Display names are context only. Phase 1 compares no additional routing details: requests that also require a separate routing identifier or another destination scheme are outside the supported contract and yield `UNCERTAIN`.

## Trust boundaries and responsibilities

### AI

Extract candidate destination identifiers and associated verbatim evidence from pasted text. Represent absence and ambiguity explicitly. A strict schema is required even if the provider offers structured output. Do not ask for a safety verdict, fraud likelihood, trust score, or verification claim. Ignore instructions embedded in input documents. Defense rests on validating outputs and restricting capabilities, not on the prompt alone.

Model output is untrusted even when syntactically valid. A matching source quote proves that text exists, not that it is a current payment instruction. Human source review is required to distinguish requested destinations from historical, quoted, canceled, or hypothetical destinations.

### Deterministic application

Enforce schema, source evidence, bounds, supported formats, canonicalization, comparison ordering, immutable snapshots, and verification preconditions. All state transitions run on the server. A browser cannot set `VERIFIED`, replace baseline IDs, or post an arbitrary comparison result.

### Human

Establish baseline trust; select the vendor; inspect the source and proposed extraction; and independently confirm changed details. Contact the vendor using a channel recorded before this request, such as a known phone number. Replying to the suspicious email or calling a number supplied only in that request does not meet the product's independent-verification requirement.

The server can enforce use of a previously recorded contact reference and collect an attestation. It cannot prove a call happened or that the person contacted was truthful. Never portray self-reported verification as automated proof. An operator label supplies audit attribution in the single-user prototype; it is not enterprise identity assurance.

### Browser, server, provider, and host

- Treat pasted HTML, extracted values, and notes as hostile display content; escape all rendering. Do not fetch links or attachments referenced by the source.
- The external extraction provider receives the pasted source. Clearly disclose this before submission. Use only synthetic data for the public hackathon demonstration. Credentials stay server-side; source text never appears in routine logs or URL query strings.
- Use one secret-backed operator session, CSRF tokens, and same-origin requests. No registration, roles, SSO, or user administration.
- Host access and the local volume are trusted operational boundaries. Bind privately or place the service behind a restricted HTTPS endpoint. A public interactive demo must contain only synthetic data and use the same operator gate; do not publish an unauthenticated writable financial-data tool.
- Give the running process access only to its data directory and provider secret. Apply provider timeout, request-size limits, and a conservative per-session request rate limit to bound cost.

## Failure handling and state integrity

| Failure | Required behavior |
| --- | --- |
| Provider timeout, outage, invalid JSON/schema, missing evidence, fabricated identifier | Persist a sanitized attempt failure and `UNCERTAIN`; permit explicit retry as a new attempt |
| No provider configured | Use clearly labeled fixture mode for synthetic demo, or return extraction unavailable; never silently simulate live extraction |
| Missing baseline or prior trusted contact | `UNCERTAIN`; ask operator to establish trust independently |
| Invalid, masked, conflicting, unsupported, or incomplete destination | `UNCERTAIN`; retain source and explanation |
| Payload over limits | Reject submission with a clear validation error; do not truncate and compare |
| Baseline changed after comparison | Keep historical comparison; reject new verification against the stale revision and require a fresh comparison |
| Source review/candidate changed after comparison | Create a new comparison; earlier verification does not carry forward |
| Contact revision changed after comparison | Require a fresh comparison against the new baseline/contact revision; do not accept a contact supplied by the request |
| Database write failure or exhausted disk | Report operation failure; do not display a persisted result or verification that was not committed |
| Double submission or browser retry | Unique verification per comparison and idempotent server handling; return the existing event |
| Operator cannot reach the vendor or receives conflicting confirmation | Leave `VERIFY` unresolved; record a note without creating `VERIFIED` |

Atomic verification checks the current revision, complete supported destination, stored comparison eligibility, trusted contact reference, and explicit attestation within the same transaction. Concurrent/stale submissions must fail cleanly. No background retry may create a verification event.

## Testing strategy

Implement tests for the risk-bearing contracts, not for every template or wrapper.

- Table-driven comparator tests: exact matches; spaces/case; a different valid IBAN; one-character corruptions; missing baseline; unsupported country/scheme; masked/truncated values; punctuation; Unicode lookalikes; checksum failures; duplicates; conflicting destinations. Every fixture has a fixed expected result and reason.
- Extraction validation tests with fake provider responses: fabricated quote/value, bad offsets, malformed schema, extra verdict/status fields, provider failure, prompt-injection text, historical account mentioned alongside new instructions. Assert no failure path produces `UNCHANGED` or `VERIFIED`.
- Lifecycle integration tests with temporary SQLite: persist/reload provenance; source correction creates a new comparison; untrusted contact rejected; stale baseline rejected; unresolved `UNCERTAIN` rejected; explicit verification succeeds and survives restart; duplicate submission is idempotent; failed writes do not appear successful.
- Request tests: forged status fields do not grant verification, CSRF protection applies to writes, input limits reject truncation, and source HTML is escaped.
- One manual end-to-end acceptance walkthrough using the minimum slice below. No live provider is required for CI; separately smoke-test one live extraction if configured.

Release gate: all deterministic and lifecycle tests pass; the changed-account walkthrough preserves `VERIFY` until a valid human event; every displayed decision links to its stored source and baseline evidence. A failing gate blocks the demo release rather than weakening a rule.

## Benchmark strategy

Create a versioned synthetic corpus of 36 cases: 12 matching destinations, 12 changed valid destinations, and 12 uncertain inputs. The corpus must include spacing/case changes, valid nearby identifiers, missing identifiers, ambiguous old/new instructions, unsupported formats, malformed identifiers, missing trusted records, and embedded instructions attempting to set a verdict. Generate checksum-valid synthetic examples without real customer information.

Maintain hand-labeled destination spans, candidate roles, baseline revisions, ambiguity flags, and expected deterministic result. Independently review labels within the team. Reserve 12 cases, four per outcome, as held-out examples; do not tune prompts against them. Run the final frozen prompt/schema once on that subset, then repeat three times to expose variability if API budget permits. Report skipped runs explicitly.

Measure separately:

1. **Extraction:** exact canonical destination accuracy, destination-span validity, missing/hallucinated candidate counts, and ambiguity recall. Do not report model confidence as accuracy.
2. **Comparison:** correctness on gold reviewed inputs; require 100% agreement across the full deterministic corpus.
3. **End-to-end before human correction:** observed outcome agreement and every false `UNCHANGED` on changed or uncertain sources. Record human corrections separately so they do not inflate AI accuracy.
4. **Operational:** extraction failure rate, median/max latency, and per-run estimated provider cost with configured model/pricing assumptions recorded.

Require zero false `UNCHANGED` in the release corpus and zero AI-created `VERIFIED` events. If extraction fails that gate, disable live extraction for the demo and demonstrate the human-reviewed fixture/manual path; report the limitation. Passing 36 cases is a regression gate, not evidence of real-world fraud detection performance. Do not compute fraud precision/recall or claim a fraud classifier.

## Minimum deployable vertical slice

One page shows one seeded synthetic vendor with a valid trusted IBAN and a previously trusted contact. The operator pastes a synthetic request with a different valid IBAN. Extraction returns the new value and an exact quote; the operator reviews it. The comparator returns `VERIFY`, shows old/new identifiers and provenance, and offers independent verification through the stored contact. A deliberate human attestation creates a scoped `VERIFIED` event while the underlying comparison stays `VERIFY`. Restarting the service preserves both records.

Also demonstrate a matching request (`UNCHANGED`) and an ambiguous or incomplete request (`UNCERTAIN`). Clearly label synthetic contacts and simulated verification in fixture demos. Include an extractor-disabled/manual source-review path for reproducibility; it uses the same evidence checks and comparator and is clearly marked as manually extracted.

Deploy one container with the Python service, SQLite on a persistent mounted directory, server-side secrets, and restricted HTTPS access. An ephemeral-disk host is unsuitable for this slice unless a persistent volume is added. Run schema creation from a small versioned SQL file, not a migration framework. Back up the database before any later schema change. Provide a documented manual retention/deletion procedure for the prototype; no indefinite-storage promise.

Suggested three-day sequence: day 1 establishes data contracts, baseline entry, manual source review, and comparator tests; day 2 adds one extractor, case UI, and human verification; day 3 runs benchmarks, verifies persistence/access controls, and deploys the synthetic demonstration. Cut input formats and UI polish before cutting evidence or human verification requirements.

## Explicit non-goals

- Generic phishing detection, email-security gateways, spam filtering, or sender reputation.
- Banking connections, payment execution, payment approval, fraud classification, autonomous agents, or AgentGate.
- Mailbox integrations, inbox monitoring, PDF/image ingestion, OCR, attachments, or outbound messages.
- Automatic vendor resolution, baseline learning, inferred trust, or automatic updates to payment destinations.
- Enterprise accounting, invoice reconciliation, accounting-system integrations, bulk processing, or dashboards unrelated to this comparison.
- Multi-tenant operation, complex authentication, roles, approval chains, and enterprise identity assurance.
- Microservices, Kubernetes, queues, distributed workers, event buses, vector retrieval, fine-tuning, or multi-provider routing.
- Legal/compliance certification, authenticated bank ownership, cryptographic document authenticity, or guarantees that unchanged details are safe.

### PHASE-1 ARCHITECTURE DECISION

Implement exactly these capabilities in Phase 1:

1. One Python service, server-rendered UI, one gated operator session, and persistent SQLite storage.
2. Manual vendor selection and manual trusted-baseline/contact entry with immutable revisions and trust provenance; one IBAN per vendor, GB/DE support only.
3. Bounded pasted-text ingestion, immutable source snapshots, source digests, and escaped evidence display.
4. One schema-constrained AI extraction adapter, explicit synthetic fixture mode, and a manual source-review fallback using the same evidence contract.
5. Required human source review, exact evidence validation, deterministic IBAN comparison, and only `UNCHANGED`, `VERIFY`, or `UNCERTAIN` comparison results with reasons.
6. One explicit independent-verification form that records a scoped `VERIFIED` event, enforces the stored trusted contact and stale-revision checks, and preserves the original comparison.
7. Append-only application provenance/events, atomic persistence, duplicate-submission handling, and clean failure behavior.
8. Risk-focused unit/integration/request tests, the 36-case synthetic benchmark, the three-outcome acceptance demonstration, and deployment to one persistent-volume host with restricted access.

Wait until Phase 2, only if Phase 1 passes its release gates and time remains:

- PDF text ingestion with page-level evidence; add OCR only with explicit uncertainty and source-image review.
- Additional IBAN countries or a second payment scheme, each with explicit format/routing rules and benchmark fixtures.
- Multiple legitimate destinations per vendor and a dedicated human baseline-replacement workflow that never learns from a verification automatically.
- Basic case search/export and improved verification evidence capture, with retention requirements defined first.

Wait until Phase 3, only after evidence from real workflows justifies the scope:

- Multi-user identity and authorization, tenant isolation, durable migrations, managed database deployment, and a stronger audit/retention model.
- Read-only mailbox/accounting ingestion with narrowly scoped permissions and explicit vendor mapping.
- Larger independently labeled evaluations and operational monitoring using consented, appropriately handled data.

Payment execution, autonomous approval, fraud/safety verdicts, and AI-created verification remain outside PayProof in every phase.
