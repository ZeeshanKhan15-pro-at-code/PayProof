# Phase-1 structured evidence extraction

Status: implemented. The canonical v1 contracts and comparison safety model remain unchanged. Extraction creates observations and provenance, never a comparison state, fraud score, trust assertion, payment approval, or human verification.

## Public contract

The service accepts immutable `SourceDocument` snapshots created with `capture_text`. Supported Phase-1 content is UTF-8 plain-text email, invoice, notice, or other text. Visible email headers are ordinary source text; no mailbox metadata or attachments are fetched.

```python
from payproof.documents import capture_text
from payproof.extraction import extract_documents, extract_attempt

email = capture_text(email_text, operator_id="operator", kind="EMAIL")
invoice = capture_text(invoice_text, operator_id="operator", kind="INVOICE")
evidence = extract_documents((email, invoice), settings=settings)
# evidence is always PaymentRequestEvidence for valid inputs/configuration.

attempt = extract_attempt((email,), settings=settings)
# Explicit private audit access: attempt.evidence, attempt.source_digests,
# and attempt.raw_provider_response. This is a separate extraction attempt.
```

`extract_document(source, ...)` is the single-source convenience function. Optional `request_id` must be an application-owned UUID. Each call creates a fresh attempt ID and timestamp. Multiple documents are submitted together, so contradictory email and invoice observations can retain their distinct sources.

Input bounds: 1–16 unique source snapshots, 20,000 total Unicode characters, valid SHA-256 digests, and no future source capture timestamps. Invalid source envelopes raise a sanitized `ExtractionInputError` before any upload; sources are never silently truncated. Empty/blank documents are rejected by `capture_text`. An incomplete but nonempty document is valid input and can yield missing/unreadable observations.

The CLI reads each file with an 80,000-byte ceiling before UTF-8 decoding and enforces the same aggregate character/source limits. This byte ceiling accommodates 20,000 four-byte Unicode characters; it does not replace the canonical character limit.

## One provider and constrained output

The single adapter uses standard-library HTTPS with the OpenAI Responses API. Requests use `text.format.type = json_schema`, `strict = true`, every field required, and `additionalProperties = false`. The provider receives a versioned instruction prompt and the source IDs/kinds/text only. No vendor baseline, trusted callback, API key, comparison result, or operator attestation is included in document content. Tools, streaming, and background requests are disabled; `store` is false. These request conventions follow [official OpenAI structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs).

`WireExtractionPayload` in `payproof/extraction_contract.py` is a private transport schema. Each field has an extraction status and candidate list. Candidates contain only:

- `value`: a verbatim string, except the strict boolean change-claim interpretation.
- `raw_text`: the exact source phrase underlying the value.
- `source_id`: one supplied document's UUID.
- `exact_excerpt`: a contiguous quote containing `raw_text`.

The server assigns evidence IDs and derives character offsets/page metadata from the immutable sources. The model cannot supply a baseline, verdict, human identity, evidence location, or verification state. This transport adapter does not alter `PaymentRequestEvidence` or its canonical `EvidenceSpan` fields.

The API schema uses a common structural subset; local Pydantic validation still enforces lengths, UUIDs, strict types, candidate counts, status relationships, and all canonical invariants. The model is configured explicitly by the operator; no model alias is guessed or substituted. It must support Responses API structured output. Provider rejection of the chosen model/schema is a failure, never a downgrade to free-text/JSON-only guessing.

Prompt version: `extract-evidence-v1`. The prompt requires literal source observations, explicit absence, source context, and retained alternatives. Instructions inside documents are untrusted data. Prompt instructions alone do not establish safety; the provider has no tools or state privileges and every returned observation passes server validation.

## Observation and evidence rules

All twelve canonical fields are required: vendor name, sender, reply-to, invoice number, amount, currency, bank, account, routing, explicit destination scheme, change claim, and stated reason. No context is filled from a baseline or inferred from another field.

| Condition | Representation |
| --- | --- |
| One supported interpretation from explicit source text | `FOUND`, one candidate and exact evidence |
| Distinct unresolved alternatives | `AMBIGUOUS`, at least two sourced candidates |
| No explicit observation | `MISSING`, empty candidates |
| Cannot read/interpret reliably | `UNREADABLE`, empty candidates |
| Extractor cannot represent the observation | `UNSUPPORTED`, empty candidates |

Unsupported/invalid **destination values** are still preserved as raw observations when visible. Extraction never validates bank ownership or repairs an account. Account spaces, dashes, Unicode lookalikes, truncation, and masked digits survive exactly. A dashed IBAN may be `FOUND` as evidence while failing the separate normalized identity contract. Missing digits are never reconstructed.

Amounts/currencies remain literal strings. For `US$ 1.234,50`, observations can retain amount `1.234,50` and currency `US$`; the extractor cannot infer `USD` or perform money arithmetic. Missing reply-to is not replaced with the sender. A bank name or destination-scheme label is not invented from the identifier.

`claims_details_changed` is `true` only for an explicit claim and `false` only for an explicit denial, each with a source phrase. Absence is `MISSING`, not false. Semantic interpretation of that phrase remains untrusted and must be checked during source review.

Every candidate, including contextual fields, must bind to an existing source with a matching exact excerpt. String `value` must equal `raw_text`, which must occur within the excerpt. The excerpt must appear exactly once within its source; the server derives zero-based Unicode character offsets from that match. Repeated excerpts require more context; the adapter does not pick a location arbitrarily. The source's supplied page metadata is copied, never generated by AI.

After conversion, both `PaymentRequestEvidence` and source-bound `CaseContract` validation run. This validates source presence, not authenticity, account ownership, payment-instruction relevance, or extraction completeness. Human source review remains required before any decisive comparison.

## Modes, bounds, and failure behavior

| Mode | Behavior |
| --- | --- |
| `disabled` (default) | No network call; `NOT_ATTEMPTED / NOT_CONFIGURED` with unreadable fields |
| `fixture` | Accept only an exact bundled synthetic source of the same kind; rebind evidence to the new source and label `FIXTURE`. Unrecognized/multi-source inputs return `NOT_CONFIGURED`; no live fallback |
| `live` | One OpenAI request using explicit key/model configuration |

Set `PAYPROOF_EXTRACTION_MODE=live`, `PAYPROOF_PROVIDER_API_KEY`, and `PAYPROOF_PROVIDER_MODEL` through the environment. Live configuration without a nonblank key/model fails startup with a sanitized configuration error. No provider credential is committed, shown in settings dumps/reprs, placed in request document content, or returned by the CLI.

Requests and complete responses are capped at 262,144 bytes. Output is capped at 8,000 tokens, 16 candidates per field, and 64 candidates total. The configurable socket I/O timeout is 1–60 seconds (default 30); it is not a hard process-wide wall-clock deadline. Requests go only to the fixed HTTPS endpoint; redirects are blocked to avoid forwarding source text or authorization to another host. There is no automatic retry or silent fixture fallback.

| Failure | Canonical failure code |
| --- | --- |
| Socket timeout | `TIMEOUT` |
| HTTP error, rate limit, connectivity failure, broken HTTP read | `PROVIDER_UNAVAILABLE` |
| Refusal, incomplete output, invalid envelope/JSON/schema/types/cardinality, unexpected verdict fields, oversized response | `INVALID_RESPONSE` |
| Fabricated raw value/quote, undeclared source, value rewriting, or non-unique excerpt | `EVIDENCE_INVALID` |
| Disabled/unconfigured extraction or unknown explicit fixture | `NOT_CONFIGURED` |

Any failed attempt returns a valid canonical record with failure metadata and **all fields `UNREADABLE`, empty candidates**. Partial success is not silently accepted when another field is invalid. Missing fields in an otherwise successful response remain `MISSING` and do not imply provider failure. No extraction record contains `UNCHANGED`, `VERIFY`, `UNCERTAIN`, or `VERIFIED` as a decision; the future deterministic engine maps extraction failures to uncertainty.

Completed/incomplete/refused responses must be handled separately from schema data; refusals need not match the requested schema according to [official OpenAI documentation](https://developers.openai.com/api/docs/guides/structured-outputs). Only one completed assistant output containing structured JSON is accepted. Reasoning items may be ignored; tool calls and multiple output texts are rejected.

## Provenance and private audit data

Metadata includes server attempt/request IDs, attempt time, schema version, prompt version, provider, and provider-reported model when available. Failed calls retain the configured model as attempted attribution; this is not a claim that the provider completed generation. Source digests are available alongside the canonical record in `ExtractionAttempt`.

The attempt retains a bounded complete provider response as private bytes when available, including invalid/refused output for later audit. It never contains locally added authorization headers. No HTTP error body, oversized/truncated body, or partial network read is retained as complete output. Raw bytes and canonical source-derived values are excluded from the attempt repr and never logged by this layer. They are still sensitive: do not serialize the whole dataclass with a generic `asdict` logger.

Persistence is not implemented in this mission. The future SQLite workflow must explicitly store these audit bytes privately together with the immutable sources/digests and canonical attempt record. Convenience functions returning only evidence intentionally do not return raw audit bytes; use `extract_attempt` for eventual persistence. Runtime source or API response text never appears in exception messages or routine logs from this layer.

## Running extraction

For explicitly configured live extraction (plain source content will be sent to OpenAI):

```bash
.venv/bin/python -m payproof extract --email email.txt --invoice invoice.txt
# Single input alternatives:
.venv/bin/python -m payproof extract --text request.txt
```

Output is only canonical `PaymentRequestEvidence` JSON. Exit 0 means a validated observation record with no extraction failure; exit 2 means a canonical failed attempt; exit 1 means invalid configuration/source or unavailable local input. Redirect output only to an appropriate private location. Exit 0 never means verified, authentic, or authorized to pay.

## Tests and known limitations

`make verify` runs lint/format checks, strict typechecking, all tests, initialization, existing corpus validation, and the package build/smoke test. `tests/test_extraction.py` exercises the real adapter/service boundary with synthetic HTTP responses for all ten requested scenarios:

1. Straightforward invoice with explicit contextual/payment fields.
2. Changed account plus sender/reply-to/change reason.
3. Missing account.
4. Account formatted with spaces.
5. Account formatted with dashes, preserved without repair.
6. Multiple account numbers retained as ambiguous.
7. Contradictory email and invoice with separate source references.
8. No payment details with explicit missing observations.
9. Unusual amount/currency formatting preserved literally.
10. Intentionally ambiguous instructions without selecting a winner.

Additional tests cover hallucinated evidence, injection/extra fields, malformed responses, refusals, provider errors, timeout, size bounds, duplicate quote locations, Unicode offsets, fixture attribution, and secret handling. These mocked integration tests prove validation and orchestration behavior; they do not measure live model extraction accuracy.

No API key was available during implementation, so a live provider smoke test was not run. Model/account access, real prompt performance, and the architecture's held-out benchmark remain to be evaluated with synthetic data when credentials are configured.

PDF ingestion, OCR, mailbox integrations, monetary normalization, automatic vendor matching, source review UI, persistence, and independent human verification remain outside this extraction layer. The separately implemented comparator is documented in [COMPARISON.md](COMPARISON.md). A source-grounded candidate may still be semantically wrong, historical, or misclassified. The adapter cannot prove that an AI found every relevant instruction or correctly recognized every contradiction. Human source review and the deterministic engine remain separate required controls.
