# Provider and foundation repair

Status: PARTIAL. The Featherless adapter is implemented and tested with mocked HTTP. Initially no credential/model was configured. The private file now supplies a key and `Qwen/Qwen3.8-27B`; real extraction and model-catalog attempts returned HTTP403. No successful extraction or exact-ID confirmation has been established. Do not treat mocked results as live model accuracy.

## Provider boundary

`payproof/providers.py` selects an extraction-only adapter from validated configuration. `openai` retains the Responses protocol; `featherless` uses chat completions. Neither receives the trusted baseline or callback, runs tools, chooses a payment state or creates a human verification event. The common pipeline still validates `WireExtractionPayload`, exact source IDs/excerpts/raw values, field constraints and `PaymentRequestEvidence`. Invalid output fails closed without fixture fallback.

Featherless's [official quickstart](https://featherless.ai/docs/quickstart-guide) specifies `https://api.featherless.ai/v1` and `/chat/completions`. Its [JSON example](https://featherless.ai/docs/tool-calling) uses `response_format={"type":"json_object"}`. PayProof requests that documented JSON mode and supplies the complete existing schema in the system message. This is **not a provider-enforced JSON-schema guarantee**: local strict schema and exact grounding remain authoritative. No markdown stripping, JSON repair, alternate provider retries or looser validation is used. Schema-incompatible models fail safely.

Responses requires one completed text item; chat completions requires one assistant choice, `finish_reason=stop`, JSON string content and model metadata, without tool calls/refusals. Truncated/multiple/malformed choices are rejected. Existing bounded bytes/tokens, no redirects, one synchronous call and timeout/network error handling remain. Timeout is socket I/O (not an absolute wall-clock deadline). Only the selected provider's official HTTPS API root is allowed; configuration cannot redirect credentials to arbitrary URLs.

## Configuration and persistent local use

| Variable | Behavior |
| --- | --- |
| `PAYPROOF_EXTRACTION_MODE` | `disabled`, `fixture`, `live`; live requires key/model |
| `PAYPROOF_PROVIDER` | `openai` (backward-compatible default) or `featherless` |
| `PAYPROOF_PROVIDER_BASE_URL` | Official API root matching selected provider; default inferred if absent |
| `PAYPROOF_PROVIDER_API_KEY` | Secret; private environment only |
| `PAYPROOF_PROVIDER_MODEL` | Exact provider model ID; no guessed/default model |
| `PAYPROOF_EXTRACTION_TIMEOUT_SECONDS` | ASCII integer 1–60, default30 |

The ignored root `.env` is created mode0600, with Featherless base URL and live mode, with key/model initially blank and later configured privately. Zeeshan must edit that private file in his local editor, not `.env.example`, source files or chat. Normal local `make serve` uses `scripts/run_local.py`; it parses simple `NAME=value` lines without shell evaluation. Process environment overrides file defaults. No automatic global `.env` loading occurs inside contracts/tests/library code. Other local commands use:

```
.venv/bin/python scripts/run_local.py .venv/bin/python -m payproof extract --text /path/to/synthetic.txt
.venv/bin/python scripts/run_local.py .venv/bin/python scripts/smoke_live_extraction.py
```

The writable browser still independently requires distinct `PAYPROOF_OPERATOR_TOKEN` and `PAYPROOF_SECRET_KEY` (32+ characters); this adapter does not bypass access controls. Configure them privately only if using that workflow. Use host secret configuration in production, not the development file. No key goes to browser JavaScript or provider prompts.

No intended model was configured at initial inspection. The private file later selected `Qwen/Qwen3.8-27B`; it was tested first. The exact ID remains **unverified** because both catalog and extraction requests returned HTTP403. No substitute model was chosen. Use the exact owner's choice from the [official model catalog API](https://featherless.ai/docs/api-reference-models), then verify with an actual bounded extraction request. Catalog membership alone does not prove account access, JSON behavior or grounding.

## Live proof and current blocker

The smoke script exercises synthetic email+invoice → real configured provider → strict wire schema → grounded evidence → simulated source-review → deterministic comparison against a separately held seeded baseline. The simulation is explicitly labeled and creates no independent human event. It emits only provider/model, request mode, latency, schema/grounding status, failure code and comparison/reasons—not keys or raw provider responses. Fixture mode stays independently available through the seeded demo.

Initial attempt: NOT_CONFIGURED, exit2, zero calls. After private configuration, one sandbox attempt returned PROVIDER_UNAVAILABLE; two network-enabled bounded pipeline attempts returned the same safe failure (latencies0.538s and0.375s on the recorded network-enabled attempts; the earlier0.021s sandbox attempt is not provider performance). Final transport diagnostic confirmed HTTP403 on POST `/chat/completions`. Two GET `/models` diagnostics also returned403, with no explicit network-policy header marker. Issuer/account/model/edge-policy cause is UNKNOWN; a credential string is not verified authentication. Real successful extraction, schema/grounding and exact model-ID confirmation remain BLOCKED/NOT_MEASURED. No fixture result substitutes for these gates.

A nonempty credential-like value was detected in the working `.env.example` during checks and cleared without exposing it. It was not copied into documentation/tests or committed; the private file was initially blank and subsequently configured securely by the owner. No secret values are recorded here. Historical Git exposure also remains unresolved: the previously documented `.env.example` literal needs issuer revocation/synthetic-status confirmation. Do not rewrite history or assume clearing a file revokes a key.

## Gold reproduction and diagnosis

New results are saved separately under `benchmarks/phase3-foundation`, preserving all prior artifacts and frozen definitions/scoring/protocol. Before and after are gold inputs with simulated source review, not extraction results.

Held-out:72 total;56 state-correct;53 exact;24 changes;12 correctly detected VERIFY;12 changed UNCERTAIN abstentions;0 critical false UNCHANGED;0 false VERIFY;30/33 strict uncertain correctness;19 exact failures. State-only expected UNCERTAIN:33/33. Diagnostic:28/30 exact/state correct,0 critical false UNCHANGED. Neither benchmark passes.

| Cases | Diagnosis | Action |
| --- | --- | --- |
| PP-17–20, PP-41–48 | Frozen gold selects current account and ignores history. Independent source inventory sees competing identifiers and deliberately blocks decisive comparison. Four expected unchanged and twelve changed cases abstain. | Preserve ambiguity defense; independently review evaluation scope/labels in a future version, never silently relabel or bypass source inventory. |
| PP-57,58,60 | Unsupported scheme payload also fails supported IBAN validation; additional `DESTINATION_INVALID` reason causes exact mismatch, state remains UNCERTAIN. | Document additive diagnostics; preserve current semantics and frozen exact scoring. |
| PP-65–68 | Gold omission observations expect only review-required in the no-review track; competing source inventory adds destination-ambiguity. Current source-review track refuses the omitted competitor. | Keep defense; source-role/omission review is needed, not case-specific suppression. |

These are safety-policy/evaluation-contract differences, not evidence that extraction worked. The pending independent label review remains visible. No deterministic or schema defect justifies weakening conservative uncertainty in this repair.

## Verification tooling and metadata

`make verify` now invokes `scripts/verify_foundation.py`: ten independent gates continue after failures and produce a fresh, uniquely named result directory with exit codes. Overall exit remains nonzero if any gate fails. An existing output directory is rejected rather than overwriting results. Benchmarks no longer write into frozen/saved Phase1 output paths through `make verify`. Regression tests prove benchmark failure still runs build/package checks.

Package description now reflects the integrated comparison workflow rather than calling it a Phase1 skeleton. Frozen protocol files and schemas are untouched. Existing historical handoffs remain dated evidence, not edited to claim new live success.

## Remaining limitations

Supported evidence remains UTF8 plain text email/invoice/notice/text and raw EML text; no MIME attachments/PDF/OCR/MSG expansion. Live arbitrary supported text has a connected adapter but no measured model capability yet. Provider JSON mode may fail with the selected model; that must remain a safe failure. No global cost budget, absolute provider deadline, tenant access or ownership proof is added. Human verification remains separate from comparison and never implies payment authorization.

## Executed verification

Final suite: lint PASS; formatting PASS; strict typecheck PASS (38 files); tests PASS (769); configuration PASS; frozen protocol PASS; build PASS; installed wheel/migrations/gated pages/WSGI health PASS. Both gold tracks remain FAIL with the counts above; the runner still completed build/package checks and exited1 honestly. Real HTTP binding was not tested by the package smoke, and these are not clean network installs. `make demo-smoke` still produces the fixture VERIFY independently. Private `.env`: ignored, untracked, mode0600.

Current live blocker: Featherless HTTP403 on both official catalog and chat endpoints. Owner should confirm key/account API permissions and model availability privately with Featherless, and test from a normal allowed host; report only HTTP status and model ID. Do not assume invalid credentials or silently pick a different model. API-key presence is CONFIGURED, validity UNKNOWN.
