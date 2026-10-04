# PayProof canonical data contracts

Status: v1 contracts implemented and tested. These contracts refine the frozen [architecture](ARCHITECTURE.md); they do not implement application services, storage, extraction calls, a comparison engine, or UI.

The canonical implementation is [payproof/schemas.py](../payproof/schemas.py). Python uses Pydantic v2. Dependencies are pinned in [pyproject.toml](../pyproject.toml), with a complete development dependency snapshot in [requirements-dev.txt](../requirements-dev.txt). No ORM, database driver, AI SDK, or frontend dependency is introduced.

## Validation and wire conventions

- Every model rejects extra properties and is frozen. Nested collections are immutable tuples; JSON represents them as arrays. No arbitrary dictionaries or model-generated verdict fields are accepted.
- For JSON, call `Model.model_validate_json(raw_json)`. For Python, call `Model.model_validate(typed_values)` with actual UUIDs, datetimes, tuples, and the documented primitive types. Strict Python validation intentionally rejects JSON-shaped dictionaries with string UUIDs or list collections. Do not use unchecked `model_construct()` or `model_copy(update=...)` at trust boundaries.
- IDs are UUIDs. The application must generate authoritative record IDs and timestamps. Evidence IDs from an untrusted extraction are local references only until validated and assigned/accepted by the server; they confer no trust.
- Timestamps are timezone-aware UTC (`Z` or `+00:00`), never naive timestamps or nonzero offsets. The application must supply server time; schema validation does not authenticate a timestamp or reject all future times using a clock.
- Required missing observations are explicit, never empty strings, zero amounts, false claims, invented accounts, or fabricated quotes. Optional contextual metadata uses `null`. Omission of any extraction field is invalid.
- Labels/identifiers are bounded nonblank strings. Currency metadata is exactly three uppercase ASCII letters: this validates code shape, not membership in a currency registry. Amount observations remain raw source strings, e.g. `1,200.50`; no floating-point money, arithmetic, or locale interpretation exists in Phase 1.
- Trusted email/domain fields use a deliberately narrow ASCII address/domain format. They record previously trusted context; their presence does not authenticate the current sender. Raw extracted addresses remain strings so malformed or spoofed source text can still be retained.
- JSON Schema can be exported using `Model.model_json_schema()`. It describes types, required fields, bounds, literals, and forbidden extras. Custom Pydantic validators additionally enforce checksums, cross-field conditions, and cross-record relationships. A generic JSON Schema validator alone is insufficient.

For example:

```python
from payproof.schemas import CaseContract, ExtractionPayload

validated = CaseContract.model_validate_json(snapshot_json)
provider_response_schema = ExtractionPayload.model_json_schema()
stored_json = validated.model_dump_json()
```

Persist and restore through these validation boundaries. Do not trust a browser or provider merely because it can emit valid JSON.

## A. TrustedVendorRecord

One record is one immutable vendor baseline revision with one supported destination. Changes create a new revision; a verification event never updates it automatically.

| Field | Type / meaning |
| --- | --- |
| `vendor_id`, `revision_id` | UUIDs binding the vendor and exact baseline revision |
| `canonical_vendor_name` | Human-entered nonblank canonical label; no AI vendor matching |
| `trusted_email`, `trusted_domain` | Optional trusted context; if both supplied, email domain must match the declared domain |
| `callback_contact` | Required `TrustedCallbackContact` with its own ID, revision, method, contact value, provenance, and last verification time |
| `bank_name` | Optional bank label; not an ownership assertion |
| `payment_identity` | Required `NormalizedPaymentIdentity` containing raw and canonical account identifier |
| `routing_identifier` | Optional raw routing information; separate routing is represented but unsupported for decisive Phase-1 comparison |
| `currency` | Optional currency metadata; excluded from destination equality |
| `provenance` | Required `TrustProvenance` describing independently established trust |
| `last_verified_at` | Human-reported date/time the baseline instructions were last checked |

`TrustProvenance` records `source_kind`, `source_reference`, `description`, `recorded_by`, and `recorded_at`. Its source kind is one of `PRIOR_VENDOR_RECORD`, `ONBOARDING_RECORD`, `INDEPENDENT_CALLBACK`, or `SYNTHETIC_FIXTURE`; `CURRENT_REQUEST` is forbidden. The schema cannot prove that a provenance description is truthful.

`TrustedCallbackContact.method` is `PHONE`, `KNOWN_PORTAL`, or `IN_PERSON`. Phase 1 intentionally excludes replying to the current email. A known portal is a previously established human contact/source, not a bank integration; the application never fetches the contact value automatically.

Baseline/contact verification cannot predate their respective provenance. Contact verification must already be included at the baseline verification time. Within a case, baseline verification must be strictly earlier than source capture. The application must separately establish that this is information trusted before the underlying request; capture time alone cannot prove that historical fact.

Malformed/untrusted baseline input is rejected before creating a trusted record. An uncertain case can contain `baseline: null` with `BASELINE_UNAVAILABLE` or `BASELINE_INVALID`; do not coerce malformed data into a trusted baseline.

## B. PaymentRequestEvidence

Represents source observations from email, invoice text, vendor notices, or plain text. This is not a request to approve payment. Supported document kinds describe provenance, not new ingestion features: Phase 1 still accepts pasted text only.

`PaymentRequestEvidence` contains a server-assigned `request_id`, unique `source_ids`, `ExtractionMetadata`, and these required `ExtractedField` properties:

| Field | Candidate value type | Interpretation |
| --- | --- | --- |
| `vendor_name` | Raw string | Claimed vendor name; never automatic identity resolution |
| `sender_email`, `reply_to` | Raw string | Addresses actually present in the pasted source |
| `invoice_number` | Raw string | Invoice reference |
| `amount`, `currency` | Raw string | Literal source text; no currency or amount inference |
| `bank_name` | Raw string | Claimed bank label |
| `account_identifier` | Raw string | Requested account candidate, including invalid/masked/unsupported values |
| `routing_identifier` | Raw string | Separate routing identifier when stated |
| `destination_scheme` | Raw string | Scheme label if explicitly present; a valid reviewed IBAN may identify its supported scheme even when this label is absent |
| `claims_details_changed` | Strict boolean with a raw evidence phrase | Whether the source explicitly asserts or denies a change; absence is `MISSING`, never inferred `false` |
| `stated_reason_for_change` | Raw string | Explicitly stated reason; never an inferred explanation |

Each `ExtractedField[T]` has `status` and `candidates`, with the following invariant:

| Status | Candidates | Meaning |
| --- | --- | --- |
| `FOUND` | Exactly one | One extracted interpretation with evidence |
| `AMBIGUOUS` | At least two | Conflicting/alternative interpretations, each with evidence |
| `MISSING` | Empty | Source contains no extracted value |
| `UNREADABLE` | Empty | Field could not be read/extracted reliably |
| `UNSUPPORTED` | Empty | Extractor cannot represent the field in this contract |

An unsupported **destination value** can still be `FOUND` as raw text, e.g. an FR IBAN. Its presence does not make it a supported normalized identity. Preserve invalid raw observations instead of silently removing them.

Repeated equivalent account mentions need not become ambiguity: retain a representative exact span when there is one interpretation. Distinct unresolved destination instructions cannot be resolved by choosing one arbitrarily. Source review and the eventual comparator must preserve this distinction.

`ExtractionMetadata` records attempt ID, method, UTC attempt time, schema version `1`, provider/model/prompt attribution when applicable, and sanitized failure code. Methods are:

- `AI`: requires provider, model, and prompt version; forbids asserting a human operator.
- `MANUAL` or `FIXTURE`: requires an operator; forbids invented provider/model attribution.
- `NOT_ATTEMPTED`: requires `NOT_CONFIGURED` failure with no provider or human attribution.

Failure codes are `TIMEOUT`, `PROVIDER_UNAVAILABLE`, `INVALID_RESPONSE`, `EVIDENCE_INVALID`, and `NOT_CONFIGURED`. A failed attempt contains only `UNREADABLE` fields with no candidates. Retain rejected raw provider responses privately outside the validated observation record if required by the architecture; never manufacture evidence to salvage a response. A later manual correction is a new attempt/review, and storage must retain the original attempt.

`ExtractionPayload` is the provider-facing subset containing only extracted fields. Server attribution belongs in the enclosing `PaymentRequestEvidence` and must never be copied from model output. The provider has no destination comparison, baseline, review, human confirmation, or state field in its schema. Validate the payload, add server metadata, and then validate the source-bound case.

Example missing observation:

```json
{"status": "MISSING", "candidates": []}
```

## C. EvidenceSpan and SourceDocument

Each candidate contains `value` plus an `EvidenceSpan`:

| Span field | Contract |
| --- | --- |
| `evidence_id` | UUID unique within the request |
| `source_id` | UUID of a declared immutable source |
| `field` | Allowlisted field name matching the enclosing extracted field |
| `extracted_value` | Nonblank raw source phrase; must appear verbatim in the excerpt |
| `exact_excerpt` | Exact contiguous text excerpt |
| `location` | Required `char_start` / `char_end`; optional positive `page_number` |
| `extraction_status` | `FOUND` or `AMBIGUOUS`, matching the enclosing field |

Offsets are zero-based Python Unicode character offsets, with an inclusive start and exclusive end; they are not UTF-8 byte or JavaScript UTF-16 offsets. The excerpt length must equal `char_end - char_start`. A string candidate must equal the raw extracted value exactly. For a boolean claim, the raw phrase is retained while the boolean is an untrusted interpretation requiring human source review.

`SourceDocument` retains source UUID, source kind, exact UTF-8 text, SHA-256 digest, server capture time/operator, optional label, and optional source-provided page number. The digest must match the exact text. Each source and the total text in a case are bounded to 20,000 characters. A digest binds a snapshot; it does not authenticate a sender.

`CaseContract` validates that `source.text[start:end] == exact_excerpt` and that the span page equals the source page metadata. Pasted text normally has no page number. Page metadata is an extension point for future ingestion, not permission for AI to invent page locations or for Phase 1 to implement PDFs.

A standalone `EvidenceSpan` validates local shape only. It cannot prove its referenced source exists. Never accept a span as grounded without source-bound validation. Source quotes demonstrate presence, not truth or instruction relevance.

## D. NormalizedPaymentIdentity

Contains `normalization_version: "iban-gb-de-v1"`, `scheme: "IBAN"`, `raw_account_identifier`, canonical `account_identifier`, and `routing_identifier: null`.

The validator removes only ASCII spaces and uppercases only permitted ASCII letters. It rejects punctuation, tabs/newlines, Unicode lookalikes, masked identifiers, unsupported countries, incorrect country formats/lengths, and invalid MOD-97 checksums. GB supports 22-character IBANs with four bank letters; DE supports 22-character IBANs with the documented numeric layout. The supplied canonical value must exactly equal normalization of the raw value.

Examples:

```text
gb82 west 1234 5698 7654 32 -> GB82WEST12345698765432
DE89 3704 0044 0532 0130 00 -> DE89370400440532013000
```

These are synthetic/test identifiers, not evidence of an owned account. Validation establishes representational integrity only. A malformed or unsupported raw account stays in extraction evidence; it cannot become this type. Context such as names, sender, amount, currency, or bank label is deliberately absent from normalized destination equality. No fuzzy matching or account suffix comparison exists.

## E. ComparisonResult

Carries comparison/request/vendor IDs, nullable baseline revision/review IDs, rule version, UTC time, comparison state, nullable baseline/requested identity snapshots, field differences, missing information, contradictions, evidence IDs, and nonempty unique machine-readable reason codes.

States are exactly `UNCHANGED`, `VERIFY`, or `UNCERTAIN`. `VERIFIED`, `SAFE TO PAY`, `FRAUD`, and `NOT FRAUD` are invalid comparison states.

`FieldDifference` has `field`, nullable baseline/requested values, `MATCH` / `CHANGED` / `UNKNOWN`, and evidence references. Complete values must agree with equality/difference; a missing value requires `UNKNOWN`. Account values are canonical; contextual requested values retain raw extraction text. Within `CaseContract`, every non-null requested difference needs source evidence for that same field. At most one difference per field is allowed.

`MissingInformation` names the missing field, `BASELINE` / `REQUEST` side, and explanation. `Contradiction` names a field, explains the conflict, and references at least two distinct evidence spans of that field. All difference/contradiction references must be in the comparison's declared evidence and exist in the case.

Reason vocabulary:

| Reason codes | Permitted state |
| --- | --- |
| `DESTINATION_MATCH` | `UNCHANGED` only |
| `DESTINATION_CHANGED` | `VERIFY` only |
| `BASELINE_UNAVAILABLE`, `BASELINE_INVALID` | `UNCERTAIN` |
| `EXTRACTION_FAILED`, `EVIDENCE_INVALID`, `REVIEW_REQUIRED` | `UNCERTAIN` |
| `DESTINATION_MISSING`, `DESTINATION_INCOMPLETE`, `UNSUPPORTED_DESTINATION`, `DESTINATION_INVALID`, `DESTINATION_AMBIGUOUS` | `UNCERTAIN` |

Decisive results require a baseline revision, a review, both valid identities, and one account difference citing the reviewed account evidence. The state/reason must agree with exact canonical destination equality. They cannot contain unresolved missing/contradictory destination information. Contextual differences or contradictions do not establish a changed destination. The cross-record validator rejects separate routing and unresolved/non-IBAN scheme observations for decisive results.

`UNCERTAIN` permits incomplete snapshots and multiple uncertainty reasons but no decisive reason. Missing baseline/review and provider failure require corresponding reasons in the source-bound case. Other reason selection remains the future deterministic engine's responsibility; these schemas do not implement its entire decision table.

`UNCHANGED` means destination match only. `VERIFY` means changed instructions requiring independent checking. Neither approves payment or labels fraud.

## F. HumanVerificationRecord

This is only a human attestation that exact destination instructions were independently confirmed. It has no approval, fraud, bank ownership, or automatic trust field.

| Field group | Purpose |
| --- | --- |
| Verification/comparison/vendor/baseline IDs | Bind the human record to one exact comparison and baseline revision |
| Trusted contact ID/revision, callback method/value, trusted source | Freeze the previously trusted independent contact actually used |
| `checked_identity` | Exact requested destination snapshot checked |
| `what_was_checked` | Fixed `EXACT_PAYMENT_DESTINATION_INSTRUCTIONS` |
| `independently_reached_person`, `operator_id` | Human-reported contact and operator attribution |
| `human_confirmed` | Explicit JSON boolean `true`; false, integer `1`, and strings are rejected |
| `confirmed_at`, `notes` | UTC timestamp and optional bounded notes |

Do not create this record when a callback was unanswered, confirmation conflicted, or the destination remained unresolved. Notes about failed contact belong in later case/audit events, not a successful verification record.

`CaseContract` requires a decisive comparison, exact checked identity, matching vendor/baseline/contact revisions and contact/provenance snapshots, and confirmation at or after comparison time. An unresolved `UNCERTAIN` cannot receive this record. The original comparison remains unchanged. An eventual UI may derive the separate label `VERIFIED` from a valid human record; there is no model-generated status field to set.

This validates an attestation's consistency, not whether a call occurred, who owns an account, or whether the contact told the truth. A valid schema object is not evidence that an authenticated human submitted it.

## Cross-record boundary and remaining application obligations

`SourceReview` binds request and attempt IDs, operator/time, explicit boolean acknowledgement that destination instructions were checked, reviewed evidence IDs, and an optional normalized identity. A reviewed identity requires an unambiguous `FOUND` account with exact raw-value and span binding. If extraction is corrected, create a new manually attributed attempt and review; do not edit prior evidence.

`CaseContract` contains sources, evidence, nullable baseline, and optional review/comparison/verification. It verifies source grounding, unique references, chronology, immutable snapshot bindings, required destination review, and trusted-contact use. A case can exist before review/comparison. This is a validation envelope, not a persistence layout or a new lifecycle state.

The future application must still:

- Authenticate/attribute the operator, generate authoritative IDs/times, and accept verification only from an explicit human command.
- Enforce prior independent trust during baseline entry; schema strings alone cannot establish it.
- Execute the architecture's full deterministic comparison and reason-ordering rules; avoid treating successful normalization as a decision.
- Check the currently stored baseline/contact/review revisions atomically when committing verification. Internal snapshot consistency does not establish freshness against external storage.
- Enforce append-only history, unique verification per comparison, idempotency, transaction success, retention, private storage, CSRF/access controls, and raw provider-response handling.
- Require human review of instruction relevance and completeness. Evidence matching cannot establish that an AI found every payment instruction.

No database, auth service, UI, provider call, or broad product feature is implemented in this phase.

## Tests and reproducibility

Synthetic good examples are in [tests/examples.py](../tests/examples.py). The schema suite in [tests/test_schemas.py](../tests/test_schemas.py) checks all three outcomes, human confirmation, all source kinds, all extraction fields, boolean claims, ambiguity, explicit provider failure, manual/fixture attribution, JSON/Python round trips, and exported schema structure.

Malformed cases cover fabricated/shifted quotes, unknown sources/pages, reused evidence IDs, invalid checksums/countries/Unicode, wrong normalization, extra verdict/ownership fields, unsupported routing, missing evidence, inconsistent decisions/reasons, incorrect chronology, mismatched/stale snapshot IDs, callback substitution, and coerced confirmation values.

Run from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Tests run offline with synthetic data once dependencies are installed. Live model evaluation and the architecture's 36-case comparison benchmark wait for the extraction/comparison implementation; schema tests do not claim to satisfy those later release gates.
