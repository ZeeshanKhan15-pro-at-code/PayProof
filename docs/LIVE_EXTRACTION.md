# Live extraction

PayProof's existing live path uses the OpenAI Responses HTTPS adapter, canonical `PaymentRequestEvidence` and source-bound evidence validation. This mission keeps the transport schema, prompt, normalization, comparison rules and safety states unchanged. No SDK or dependency was added.

## Actual provider and configuration

The single endpoint is fixed to `https://api.openai.com/v1/responses`; the provider attribution is `openai`. There is no alternate base URL, automatic provider discovery, model substitution or fixture fallback in live mode. A credential/model for another service does not establish compatibility with this endpoint.

Configuration is read only from process environment:

| Variable | Behavior |
| --- | --- |
| `PAYPROOF_EXTRACTION_MODE` | Must explicitly be `live` for a real request; default is `disabled` |
| `PAYPROOF_PROVIDER_API_KEY` | Nonblank server credential, used only in the Authorization header |
| `PAYPROOF_PROVIDER_MODEL` | Explicit nonblank Responses-compatible model supporting strict structured output; no model default |
| `PAYPROOF_EXTRACTION_TIMEOUT_SECONDS` | Socket I/O timeout, 1–60 seconds, default 30 |
| `PAYPROOF_ENV` / `PAYPROOF_SECRET_KEY` | Production also requires the existing independently supplied signing secret |

`.env` and `.env.example` are not automatically loaded. A key in a file is not a configured process environment. Keep secret fields in the tracked example empty; supply credentials through the host's secret/environment mechanism. Do not pass keys as command arguments, paste them into source documents or enable HTTP/header debug logging. Unknown `PAYPROOF_*` variables and invalid live/production settings reject startup with sanitized errors. A model value containing the configured credential is rejected, so credential text cannot become public model metadata.

The request uses `text.format` with `json_schema` and `strict=true`. Every extraction property is required and extra properties are forbidden. Refusals, incomplete results and unsupported schema/model errors are handled as failures; the adapter does not downgrade to free text or JSON-only mode. These request and refusal conventions were checked against [official OpenAI structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

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

At initial inspection on 2026-10-05, process live mode was not selected, provider key and model were absent, and `.env` was absent. Running the smoke script returned:

```json
{"status": "NOT_CONFIGURED", "provider_called": false}
```

Exit: 2. No provider request occurred. A subsequent credential/model edit in tracked `.env.example` was detected without displaying its value. The credential field was cleared; the public model setting was preserved. The supplied value is held temporarily only in process memory pending explicit permission for a one-off file-to-subprocess-environment bootstrap. No provider call has been authorized through that bootstrap yet; the file edit never configured the existing environment automatically. The proposed live outcome is pending that choice. No live accuracy result is claimed.

The new environment-driven mocked integrations cover paired-document success, exact evidence, malformed JSON/schema, fabricated evidence, verdict fields, timeout, network error, model rejection/provider error, valid partial data, no fixture fallback, credential echo/source/model guards and unconfigured smoke. The live-path checks plus distribution safeguards now contain 22 regressions; final complete-suite results are recorded below. Six credential-handling checks were first reproduced failing, then corrected. Existing provider and red-team regressions remain intact. Final full-project validation passes: Ruff lint/format (50 files), strict mypy (26 source files), **617/617 tests**, production wheel/source build, source-archive exclusion guard and installed-wheel/console/demo/production-WSGI smoke. All 22 new live/distribution checks pass. Only documentation changed after these completed checks. Gold benchmark rerun remains 30/30 correct states and exact results, with all 10 supported changes detected and no critical false `UNCHANGED`. The optional file-to-environment live bootstrap remains awaiting permission; no provider request or model accuracy claim is recorded.

## Limitations

Exact evidence does not prove that the model retained every current instruction or recognized historical roles. The documented omission plus false-human-acknowledgement risk remains. A successful smoke would not certify provider access for all models, population extraction accuracy, bank ownership or payment safety. Arbitrary secret transformations outside supported literal/JSON representations cannot be universally detected; never include credentials in source material. Provider retention/privacy obligations are outside `store=false` and must be assessed before real customer documents are sent. Persistence, independent verification, OCR and multi-provider routing remain outside this work.

## Distribution safeguard

While this work was running, an editor save restored a credential into the tracked template after it had been cleared. A local source build copied that template into the ignored source archive. The contaminated archive was detected and deleted, and the template key was cleared again without displaying its value. No credential was committed or sent to a provider by this work.

`MANIFEST.in` now excludes `.env`, `.env.*`, private-key and certificate-key files from source distributions, including the example template. The build smoke also checks source-archive member names and rejects environment/credential files. The wheel already includes only allowlisted package assets. Two regressions exercise the archive guard. This prevents a later editor save of the template from silently embedding a key in a release artifact; it does not permit committing a nonempty key field to Git.

A further regression preserves literal source data such as `[masked account]`: source strings are never treated as required JSON documents. Strict syntax checking applies to the model's output JSON, whose undecodable audit bytes are discarded. Credentials are checked across valid decoded response strings without repairing or reinterpreting extracted source values.
