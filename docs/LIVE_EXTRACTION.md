# Current provider boundary

Featherless chat completions and OpenAI Responses now share strict local extraction/grounding. See [provider configuration and actual current evidence](PHASE3_PROVIDER_AND_FOUNDATION.md). The original Responses-specific account below describes that adapter, not Featherless. The configured Featherless model returned HTTP403; no successful live extraction has been measured in the current environment.

# Live extraction

PayProof's existing live path uses the OpenAI Responses HTTPS adapter, canonical `PaymentRequestEvidence` and source-bound evidence validation. This mission keeps the transport schema, prompt, normalization, comparison rules and safety states unchanged. No SDK or dependency was added.

## Actual provider and configuration

The OpenAI adapter uses `https://api.openai.com/v1/responses`; Featherless uses `https://api.featherless.ai/v1/chat/completions`. `PAYPROOF_PROVIDER` and its matching official `PAYPROOF_PROVIDER_BASE_URL` select the wire protocol. No automatic discovery, model substitution or fixture fallback occurs.

Configuration is read only from process environment:

| Variable | Behavior |
| --- | --- |
| `PAYPROOF_EXTRACTION_MODE` | Must explicitly be `live` for a real request; default is `disabled` |
| `PAYPROOF_PROVIDER_API_KEY` | Nonblank server credential, used only in the Authorization header |
| `PAYPROOF_PROVIDER_MODEL` | Explicit nonblank Responses-compatible model supporting strict structured output; no model default |
| `PAYPROOF_EXTRACTION_TIMEOUT_SECONDS` | Socket I/O timeout, 1–60 seconds, default 30 |
| `PAYPROOF_ENV` / `PAYPROOF_SECRET_KEY` | Production also requires the existing independently supplied signing secret |

Library calls do not automatically load `.env`; `scripts/run_local.py` explicitly loads ignored local defaults into the child process without shell execution. `.env.example` is never loaded automatically. Keep secret fields in the tracked example empty; supply credentials through the host's secret/environment mechanism. Do not pass keys as command arguments, paste them into source documents or enable HTTP/header debug logging. Unknown `PAYPROOF_*` variables and invalid live/production settings reject startup with sanitized errors. A model value containing the configured credential is rejected, so credential text cannot become public model metadata.

The OpenAI request uses `text.format` with `json_schema` and `strict=true`; Featherless requests documented JSON-object mode with the existing schema in the prompt. Both require strict local schema validation. Every extraction property is required and extra properties are forbidden. Refusals, incomplete results and unsupported schema/model errors are handled as failures; the adapter does not downgrade to free text or JSON-only mode. These request and refusal conventions were checked against [official OpenAI structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

## End-to-end boundary

```text
raw UTF-8 email/invoice -> immutable source capture and digest
                        -> configured live provider, source-only request
                        -> completed response / strict wire schema
                        -> exact quote, full-token and source validation
                        -> canonical PaymentRequestEvidence
```

The model receives document IDs, kinds and exact text, plus the extraction instructions/schema. It never receives the trusted baseline, callback contact, review, comparison result or human confirmation. It has no tools, vendor-selection command or verification command. Server IDs, offsets, page metadata and attribution are assigned locally; the model cannot supply authoritative provenance or states.

Every accepted candidate must have its exact raw value in an exact, unique source excerpt. Its source ID must exist. String values cannot be rewritten, repaired or normalized. Account excerpts must describe a complete token against original source characters, including outside a clipped quote. `PaymentRequestEvidence` and `CaseContract` validation run after conversion. Hash/quote checks establish source binding, not authenticity, instruction relevance or completeness.

All twelve fields remain mandatory. Valid partial observations use `MISSING` with no candidates; missing reply-to is not populated from sender, account digits are not invented and absent change claims are not inferred as false. Invalid partial output invalidates the whole attempt. Contradictory candidates retain their separate evidence; no source wins automatically.

Unsupported or malformed account **text** is preserved verbatim when grounded. It cannot create a supported normalized identity or decisive comparison. Unsupported model/envelope/output shapes reject the attempt. This distinction preserves evidence without granting payment confidence.

No accepted extraction record has a fraud, legitimacy, approval, safety or verification decision. Attempts to add those fields are rejected. Words in quoted source text remain data. Human source review and the deterministic engine still determine whether comparison can proceed; the model cannot create `VERIFIED`.

## Bounds and failures

Input: 1–16 unique validated sources, at most 20,000 aggregate Unicode characters, exact SHA-256 and valid chronology. Invalid sources are rejected before upload without truncation. Request/response limit: 262,144 bytes; output limit: 8,000 tokens, 16 candidates per field and 64 overall. Redirects, streaming, tools and background calls are disabled; `store=false`. There is one attempt and no automatic retry. The timeout is a socket I/O timeout, not a hard whole-process deadline.

| Condition | Behavior |
| --- | --- |
| Disabled/unconfigured extraction | `NOT_ATTEMPTED / NOT_CONFIGURED`; no provider call |
| Live startup missing key/model | Sanitized `ConfigurationError`; no request |
| Direct or URL-wrapped socket timeout | `TIMEOUT` |
| HTTP 400 model/schema rejection, 401/403, 429, 5xx, DNS/connectivity or broken HTTP read | `PROVIDER_UNAVAILABLE`; existing contract deliberately has no guessed provider-specific verdict |
| Malformed/duplicate JSON, wrong types/cardinality, refusal, incomplete/empty/oversized/unsupported output, extra verdict fields | `INVALID_RESPONSE` |
| Invented/rewritten value, fabricated/nonunique excerpt, unknown source or account fragment | `EVIDENCE_INVALID` |
| Provider response echoes configured credential, including decoded JSON/nested output strings | `INVALID_RESPONSE`; raw response discarded before canonical metadata or private audit retention |
| Source contains configured credential | Sanitized `ExtractionInputError` before upload |

Failed attempts contain all fields `UNREADABLE` with zero candidates and explicit failure metadata. They cannot receive successful source review or become a decisive result. Local malformed input/configuration remains a rejected operation rather than a fabricated model observation. `payproof extract` exits 0 for valid observations, 2 for canonical extraction failure and 1 for input/configuration failure. None means permission to pay.

The configured model is attempted attribution on failures; completed successful output records the provider-reported model. HTTP error bodies, oversize/partial network reads and credential-bearing or undecodable model JSON output are not retained as complete audit responses. Other bounded, inspectable response bytes may remain privately in memory in `ExtractionAttempt`, with repr suppression. They are not written or logged by this path. Do not generically serialize the attempt with an audit logger; canonical evidence and explicit safe metadata are the public boundary. No API key is added to request content or stored output.

## Reproduce

For operator-supplied text after securely configuring the process environment:

```bash
.venv/bin/python -m payproof extract --email email.txt --invoice invoice.txt
```

For a small synthetic live check:

```bash
.venv/bin/python scripts/smoke_live_extraction.py
```

The smoke script uses two raw synthetic documents, contains no baseline and no credentials, and calls the same adapter/schema/evidence pipeline. It requires live mode, key and model in environment; otherwise it emits `NOT_CONFIGURED`, `provider_called=false`, exit 2. It never loads a credential file or substitutes fixtures. With configuration, it outputs the canonical observations and an honest smoke assessment: PASS only for the expected source-backed account plus missing reply-to/routing/change claim; a valid but wrong/partial extraction is `SMOKE_MISMATCH`, not an inflated pass. Provider failure is `FAILED` with the existing safe code. This is one diagnostic case, not a benchmark accuracy measurement.

## Actual validation record

Current release assessment (2026-10-07): process extraction mode is disabled, provider credential/model absent. The synthetic live smoke and held-out live gate return NOT_CONFIGURED without provider calls. Live compatibility, extraction accuracy, evidence grounding rates and end-to-end state accuracy remain NOT_MEASURED. See [PHASE2_RELEASE_REPORT.md](PHASE2_RELEASE_REPORT.md) for final artifacts and separate PASS/FAIL/BLOCKED gates. No credential is queued for a file-to-environment bootstrap; `.env.example` never configures this process and its credential/model fields are blank.

Mocked integrations exercise success/partial data, exact grounding, malformed/duplicate/schema-invalid JSON, fabricated excerpts, unsupported verdict fields, timeout/network/model/provider failure and credential echo guards. They validate the real adapter path under controlled responses, not live model accuracy. Durable SQLite and gated web workflows now store canonical observations/sanitized failures and preserve failed attempts, with confirmation blocked. The full synthetic suite and distribution checks are recorded in the release report. Historical 2026-10-05 checks and earlier gold 30/30 were initial implementation evidence, not current evaluation performance; the current 72-case gold track is FAIL at 56/72 states and 53/72 exact results.

## Limitations

Exact evidence does not prove that the model retained every current instruction or recognized historical roles. The documented omission plus false-human-acknowledgement risk remains. A successful smoke would not certify provider access for all models, population extraction accuracy, bank ownership or payment safety. Arbitrary secret transformations outside supported literal/JSON representations cannot be universally detected; never include credentials in source material. Provider retention/privacy obligations are outside `store=false` and must be assessed before real customer documents are sent. Persistence and explicit independent verification are now implemented by the workflow; OCR and multi-provider routing remain outside scope. The independent source inventory blocks tested competing/reference-only regions but does not prove exhaustive discovery or current instruction intent.

## Distribution safeguard

While this work was running, an editor save restored a credential into the tracked template after it had been cleared. A local source build copied that template into the ignored source archive. The contaminated archive was detected and deleted, and the template key was cleared again without displaying its value. No credential was committed or sent to a provider by this work.

`MANIFEST.in` now excludes `.env`, `.env.*`, private-key and certificate-key files from source distributions, including the example template. The build smoke also checks source-archive member names and rejects environment/credential files. The wheel already includes only allowlisted package assets. Two regressions exercise the archive guard. This prevents a later editor save of the template from silently embedding a key in a release artifact; it does not permit committing a nonempty key field to Git.

A further regression preserves literal source data such as `[masked account]`: source strings are never treated as required JSON documents. Strict syntax checking applies to the model's output JSON, whose undecodable audit bytes are discarded. Credentials are checked across valid decoded response strings without repairing or reinterpreting extracted source values.

### Phase-2 credential-boundary red team

The extraction boundary now rejects all currently configured literal credentials (provider key, signing secret, operator passphrase) in source metadata/text before provider access, not just the provider key. Completion metadata and raw response JSON are checked before retention, including JSON-escaped/nested credential echoes. Rejected echoes become `INVALID_RESPONSE` with no retained raw response. Model configuration cannot contain any configured credential, and signing/provider secrets must differ. These safeguards do not identify every unknown, transformed or historical credential; do not submit secrets as evidence. No extraction fields, grounding rules or model decision authority changed.
