# PayProof canonical data contracts

Status: v1 contracts implemented and tested. These contracts refine the frozen [architecture](ARCHITECTURE.md). The extraction service, comparator and connected CLI are documented in [EXTRACTION.md](EXTRACTION.md), [COMPARISON.md](COMPARISON.md) and [VERTICAL_SLICE.md](VERTICAL_SLICE.md). SQLite persistence and explicit human checks are available through the local workflow CLI; the minimal gated web operator UI uses the same durable contracts.

The canonical implementation is [payproof/schemas.py](../payproof/schemas.py). Python uses Pydantic v2. Dependencies are pinned in [pyproject.toml](../pyproject.toml), with a complete development dependency snapshot in [requirements-dev.txt](../requirements-dev.txt). No ORM, database driver, AI SDK, or frontend dependency is introduced.

## Validation and wire conventions

- Every model rejects extra properties and is frozen. Nested collections are immutable tuples; JSON represents them as arrays. No arbitrary dictionaries or model-generated verdict fields are accepted.
- For untrusted JSON, call `parse_contract(Model, raw_json)` from `payproof.validation`: it rejects duplicate keys and invalid JSON before strict Pydantic validation. Direct `Model.model_validate_json()` is suitable for trusted application-generated JSON, not an ambiguous external payload. For Python, call `Model.model_validate(typed_values)` with actual UUIDs, datetimes, tuples, and the documented primitive types. Strict Python validation intentionally rejects JSON-shaped dictionaries with string UUIDs or list collections. Do not use unchecked `model_construct()` or `model_copy(update=...)` at trust boundaries.
- IDs are UUIDs. The application must generate authoritative record IDs and timestamps. Evidence IDs from an untrusted extraction are local references only until validated and assigned/accepted by the server; they confer no trust.
- Timestamps are timezone-aware UTC (`Z` or `+00:00`), never naive timestamps or nonzero offsets. The application must supply server time; schema validation does not authenticate a timestamp or reject all future times using a clock.
- Required missing observations are explicit, never empty strings, zero amounts, false claims, invented accounts, or fabricated quotes. Optional contextual metadata uses `null`. Omission of any extraction field is invalid.
- Labels/identifiers are bounded nonblank strings. Currency metadata is exactly three uppercase ASCII letters: this validates code shape, not membership in a currency registry. Amount observations remain raw source strings, e.g. `1,200.50`; no floating-point money, arithmetic, or locale interpretation exists in Phase 1.
- Trusted email/domain fields use a deliberately narrow ASCII address/domain format. They record previously trusted context; their presence does not authenticate the current sender. Raw extracted addresses remain strings so malformed or spoofed source text can still be retained.
- JSON Schema can be exported using `Model.model_json_schema()`. It describes types, required fields, bounds, literals, and forbidden extras. Custom Pydantic validators additionally enforce checksums, cross-field conditions, and cross-record relationships. A generic JSON Schema validator alone is insufficient.

For example:

```python
from payproof.schemas import CaseContract, ExtractionPayload
from payproof.validation import parse_contract

validated = parse_contract(CaseContract, snapshot_json)
canonical_observation_schema = ExtractionPayload.model_json_schema()
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

Source ID lists/cases allow at most 16 sources, each field at most 16 candidates, and an extraction at most 64 candidates overall. Manual/cached records receive the same bounds as live extraction.

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

`ExtractionPayload` is the canonical observation subset containing only extracted fields. The live adapter uses the private `WireExtractionPayload` transport format, derives canonical spans from exact source quotes, and then creates this canonical shape. Server attribution belongs in the enclosing `PaymentRequestEvidence` and must never be copied from model output. The provider has no destination comparison, baseline, review, human confirmation, or state field in its schema. Validate the transport payload, derive/validate canonical evidence, add server metadata, and then validate the source-bound case. See [EXTRACTION.md](EXTRACTION.md) for the implemented transport boundary.

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

Account quotes additionally require lexical completeness against original source characters, including outside clipped excerpts. A trusted IBAN quoted as part of a longer identifier is rejected, including attached identifier/marker characters, dotted continuations, Unicode connectors/dashes/math symbols and following numeric groups separated by horizontal whitespace. Complete malformed raw values remain representable for normalization to reject. This does not discover omitted accounts or decide instruction roles; see [PHASE1_REDTEAM.md](PHASE1_REDTEAM.md).

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

`UNCERTAIN` permits incomplete snapshots and multiple uncertainty reasons but no decisive reason. Missing baseline/review and provider failure require corresponding reasons in the source-bound case. The implemented deterministic engine selects reasons in the stable order documented in [COMPARISON.md](COMPARISON.md); schemas constrain rather than execute the entire decision table.

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

Do not create this record when a callback was unanswered, confirmation conflicted, or the destination remained unresolved. Notes about failed contact belong in persisted `IndependentCheckEvent` attempt events, not a successful verification record.

`CaseContract` requires a decisive comparison, exact checked identity, matching vendor/baseline/contact revisions and contact/provenance snapshots, and confirmation at or after comparison time. An unresolved `UNCERTAIN` cannot receive this record. The original comparison remains unchanged. `StoredCase.independent_verification_status` derives the separate label `VERIFIED` only from a fresh positive human record; there is no model-generated status field to set.

This validates an attestation's consistency, not whether a call occurred, who owns an account, or whether the contact told the truth. A valid schema object is not evidence that an authenticated human submitted it.

## Cross-record boundary and remaining application obligations

`SourceReview` binds request and attempt IDs, operator/time, explicit boolean acknowledgement that destination instructions were checked, reviewed evidence IDs, and an optional normalized identity. A reviewed identity requires a `FOUND` account or multiple `AMBIGUOUS` observations that **all** normalize to the same valid supported IBAN. Every account span must be reviewed; the identity's raw representation must exactly equal one observed value. Distinct destinations cannot be resolved by selecting one candidate. Decisive results must cite every account span, and every explicit supported scheme span must also be reviewed. Repeated ASCII case/space variants of `IBAN` are supported. This refinement implements the architecture's requirement that repeated mentions of one canonical destination are not conflicting. If extraction is corrected, create a new manually attributed attempt and review; do not edit prior evidence.

`CaseContract` contains sources, evidence, nullable baseline, and optional review/comparison/verification. It verifies source grounding, unique references, chronology, immutable snapshot bindings, required destination review, and trusted-contact use. A case can exist before review/comparison. This is a validation envelope, not a persistence layout or a new lifecycle state.

Remaining application obligations (the local durable workflow below implements revision checks, authoritative audit times, and append-only transactions):

- Authenticate/attribute the operator, generate authoritative IDs/times, and accept verification only from an explicit human command.
- Enforce prior independent trust during baseline entry; schema strings alone cannot establish it.
- Invoke the implemented deterministic comparator on source-bound snapshots with authoritative IDs/times; avoid treating successful normalization as a decision.
- Check the currently stored baseline/contact/review revisions atomically when committing verification. Internal snapshot consistency does not establish freshness against external storage.
- Enforce append-only history, unique verification per comparison, idempotency, transaction success, retention, private storage, CSRF/access controls, and raw provider-response handling.
- Require human review of instruction relevance and completeness. Evidence matching cannot establish that an AI found every payment instruction.

The schema layer implements no database, auth service, UI, or provider call. The separately implemented provider adapter and source grounding are documented in [EXTRACTION.md](EXTRACTION.md).

## Tests and reproducibility

Synthetic good examples are in [tests/examples.py](../tests/examples.py). The schema suite in [tests/test_schemas.py](../tests/test_schemas.py) checks all three outcomes, human confirmation, all source kinds, all extraction fields, boolean claims, ambiguity, explicit provider failure, manual/fixture attribution, JSON/Python round trips, and exported schema structure.

Malformed cases cover fabricated/shifted quotes, unknown sources/pages, reused evidence IDs, invalid checksums/countries/Unicode, wrong normalization, extra verdict/ownership fields, unsupported routing, missing evidence, inconsistent decisions/reasons, incorrect chronology, mismatched/stale snapshot IDs, callback substitution, and coerced confirmation values.

Run from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Tests run offline with synthetic data once dependencies are installed. Normalization/comparison tests and ten-fixture gold comparison and CLI integration are implemented; see [COMPARISON.md](COMPARISON.md). Live held-out model evaluation and independent review of the 72-case held-out corpus remain later gates; persistent local verification lifecycle tests now run in `tests/test_persistence.py`.

## Durable local workflow (Phase 2)

`payproof/storage.py` implements the previously reserved SQLite boundary using the standard library. `payproof/workflow_contracts.py` adds strict local command/envelope contracts without changing the extraction schema or comparison states. `payproof/verification.py` exports the human command contracts; the transaction lives in `SQLiteStore.record_independent_check`.

### New contracts

- `CaseInputs`: original frozen sources plus canonical extracted evidence. No baseline, review, comparison, verification, status, or callback override is accepted. Grounding and chronology are revalidated in `CaseContract` on every write/read. JSON import is a source-bound manual/developer ingestion path, not an attestation. Imports reject duplicate object keys/nonfinite JSON and are bounded to 4 MiB.
- `IndependentCheckAction`: unique action UUID, operator, exact-instructions check, explicit boolean `independently_checked: true`, outcome (`CONFIRMED`, `NOT_CONFIRMED`, `INCONCLUSIVE`), human-reported person/role (required for confirmation), optional notes. No client timestamp, checked destination, trusted callback or verdict is accepted. The CLI requires a final explicit acknowledgement with no default confirmation.
- `IndependentCheckEvent`: server UUID/time, source case revision, comparison/baseline IDs, frozen previously trusted contact/provenance, exact compared destination, action/outcome/person/operator/notes, optional positive `HumanVerificationRecord`. Only a confirmed event may contain a positive record. Every outcome is retained; an unanswered or inconclusive check never derives `VERIFIED`.
- `StoredCase`: authoritative case/revision UUIDs, monotonic version, selected vendor ID, recorded time, validated `CaseContract`, engine fingerprint and current head identifiers. `stale` and `independent_verification_status` are derived properties, not writable fields. Historical records remain visible but report `STALE`; `VERIFIED` is never a comparison/extractor state.

### Database and freshness rules

The packaged `migrations/001_initial.sql` creates schema version 1 (`PRAGMA user_version` and migration ledger). Initialization is idempotent; unknown versions and nonempty unversioned databases fail closed. No migration framework or ORM is added. Back up before introducing any future migration.

Immutable tables retain vendor/contact revisions, original source metadata/text and hash, extraction attempts with all observations/spans, complete case snapshots including reviews/comparisons, workflow audit events, independent-check attempts, and positive confirmations. Separate vendor/case head pointers identify current revisions. Snapshots/events reject SQL update/delete, and case versions cannot move backwards. These guards prevent accidental rewriting, not tampering by a privileged database administrator. SHA-256 snapshot checks detect accidental corruption; they are not signatures.

Each mutation uses `BEGIN IMMEDIATE`, foreign keys, WAL and `synchronous=FULL`. Server-generated case revision/event/confirmation IDs and UTC times are committed atomically with the audit event and head update. A failed write claims no success and rolls back. Every case mutation requires its expected current revision. Vendor replacement requires the expected vendor revision; old vendor revisions cannot be restored as the head. Same source UUID, extraction-attempt UUID or contact revision with different facts is rejected. Corrections need new source/attempt/contact IDs or revisions as appropriate, and never edit old observations.

Verification additionally requires a reviewed, current decisive comparison, the current vendor/contact snapshot and an unchanged safety-engine fingerprint. The contact and exact checked identity are obtained exclusively from stored trusted baseline and comparison data; suspect sender/reply-to/contact fields cannot substitute them. Engine fingerprint covers comparison, normalization, schemas and instruction-safety code. Source, extraction, review, comparison or trusted-record changes invalidate prior verification eligibility. Replacing/refreshing inputs clears current review/comparison/confirmation but retains history. Refresh against a newer baseline never backdates it: if trust no longer predates source capture, it is rejected, requiring properly established earlier history or a new genuine source capture.

A repeated identical human action UUID against the original revision returns its existing event only while that resulting revision is still current and fresh. A changed payload or stale retry is rejected. Positive confirmation is unique per comparison. Negative outcomes are audit events, and a later new action can confirm using the new current revision. Confirmation never updates the trusted vendor record automatically.

### Commands and authority

All commands use `PAYPROOF_DATA_DIR` (default `data/`) and `payproof.sqlite3`. Database mode is `0600`; a newly created data directory uses `0700`. Existing directory permissions and volume placement remain the local operator's responsibility. No API key, configuration secret, raw rejected provider response or provider request headers are stored. Validated source text itself may be sensitive; use synthetic data for demonstrations.

```bash
.venv/bin/python -m payproof workflow init
.venv/bin/python -m payproof workflow vendor-add --file payproof/fixtures/trusted_vendors/demo-account-3821.json --operator local-human
.venv/bin/python -m payproof workflow case-create --vendor-id VENDOR_UUID --email synthetic-email.txt --invoice synthetic-invoice.txt --operator local-human
# Alternatively import a JSON CaseInputs (sources + evidence only):
.venv/bin/python -m payproof workflow case-import --vendor-id VENDOR_UUID --file case-inputs.json --operator local-human
.venv/bin/python -m payproof workflow show --case-id CASE_UUID
.venv/bin/python -m payproof workflow review --case-id CASE_UUID --revision-id CURRENT_REVISION_UUID --operator local-human
.venv/bin/python -m payproof workflow compare --case-id CASE_UUID --revision-id CURRENT_REVISION_UUID --operator local-human
.venv/bin/python -m payproof workflow verify --case-id CASE_UUID --revision-id CURRENT_REVISION_UUID --operator local-human
.venv/bin/python -m payproof workflow events --case-id CASE_UUID
# After a trusted-record change, refresh then repeat review and comparison:
.venv/bin/python -m payproof workflow refresh --case-id CASE_UUID --revision-id CURRENT_REVISION_UUID --operator local-human
```

Use the new revision UUID printed by each command for the next action. `replace --file case-inputs.json` stores corrected observations; `vendor-add --expected-revision UUID` stores a newly identified trusted revision. `show` displays all original sources, competing source candidates, extracted spans, trusted provenance, comparison and separately labeled freshness/attestation. `events` displays every independent-check outcome. Historical snapshots are accessible through `get_case(case_id, revision_id)`; workflow events also retain every source-review/comparison transition.

`case-create` uses the existing configured extraction mode and exact grounding checks, outside the database transaction; it atomically checks that the baseline did not change during extraction. Live mode has no fixture fallback. Failed extractions can be persisted and compared to `UNCERTAIN`; they cannot be successfully reviewed or confirmed. Settings remain environment-only, with existing validation; this command does not load `.env`.

The CLI is intentionally local and human-operated. File/OS access is the authority boundary, and operator labels are attribution, not authenticated identity. The gated web forms now enforce a secret-backed operator session, CSRF and same-origin checks before calling these commands. Multi-user identity, roles and public deployment remain unimplemented. Do not expose the local Python command as an unauthenticated web action. No AI/provider/comparator path invokes the human command. PayProof records the person's attestation; it cannot prove a callback occurred, contact identity, bank ownership, fraud, legitimacy or payment safety.

### Retention and validation

Keep the database and backups on private persistent local storage; Git ignores database files and the default data directory. Use SQLite's online backup API for a consistent backup (or stop all writers and preserve the database plus any WAL). To delete a synthetic demonstration, stop every process and delete that dedicated store and its `-wal`/`-shm` files and backups. Per-case retention/deletion is not implemented; immutable history is retained until the dedicated store is removed. No indefinite-retention claim is made.

`tests/test_persistence.py` exercises restart durability, positive/negative/inconclusive outcomes, callback binding, strict action fields, stale revisions across connections, trusted-contact immutability, engine changes, idempotency, duplicate confirmation, transaction rollback, snapshot corruption and interactive cancellation/confirmation. The installed-wheel smoke also initializes and reopens SQLite from packaged migration SQL. Run `make lint`, `make typecheck`, `make test` and `make build`; no provider or payment integration is required for these tests.

The [minimal web workflow](WEB_WORKFLOW.md) adds no comparison or extraction contracts. Operator identity is taken from the signed session, case revisions from explicit form bindings, and callback data only from the current stored baseline. Unknown/duplicate form fields (including posted states, contacts and operator overrides) are rejected. All original source text, extracted values, notes and history are rendered with Jinja autoescaping.

## Human-established baseline workflow and receipts

SQLite migration2 adds immutable `baseline_drafts`, `baseline_assertions` and `workflow_submissions`. Migration1 data remains intact and upgrade/restart is idempotent. Drafts retain original source text/digests/capture metadata and schema-validated extraction observations or an explicitly manual full supported destination. A draft is not a TrustedVendorRecord. Failed, incomplete or competing destination evidence cannot be promoted.

An explicit BaselineAssertion binds source review, deliberate prior trust and independently established contact to the draft. Server-generated vendor/contact revision IDs and the server assertion timestamp are persisted atomically; operator attribution is supplied from the current workflow session. The claimed prior-check date is separate from the actual recorded assertion timestamp. Provenance references the draft and the human's prior source description. Selecting/uploading the first document cannot assert trust.

Repeated identical assertions reuse the recorded result; changed assertion payloads and stale vendor revisions are rejected. Case submission hashes/IDs prevent duplicate creation, and expected case/vendor revisions guard extraction commits. Existing review/comparison/human-check contracts remain authoritative; no model or client supplies comparison state, confirmation timestamp or trusted callback.

HTML/JSON receipts are derived from persisted IndependentCheckEvent records with current/stale status calculated from case/vendor/engine revisions. The receipt includes the immutable CaseContract snapshot at the event source revision, its case version/revision, recorded comparison state and generation timestamp. Comparison ID, baseline revision, trusted contact and checked identity must match the event; a mismatch fails closed. Historical receipts never substitute newer trusted values or source evidence. Printable HTML retains exact excerpts, independent source context and source references/digests; printed status cannot update after later revisions. They retain exact destination, trusted contact origin, comparison and human outcome. Receipts explicitly do not provide payment authorization or bank ownership verification and are not cryptographically certified documents. Public workspaces use the same contracts inside isolated temporary stores; anonymous-human attribution is not proof of an identified person.
