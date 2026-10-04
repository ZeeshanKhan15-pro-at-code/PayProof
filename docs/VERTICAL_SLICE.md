# Input-to-evidence CLI workflow

The connected local CLI uses the existing canonical contracts, extraction service, normalizer and deterministic comparator. It displays trusted/requested values, differences, exact evidence, provenance, state, reason codes and the previously trusted callback.

## Run the seeded demo

```bash
make demo
```

Read all displayed source text and evidence, then type `REVIEWED` to acknowledge source review.

| Value | Identity/source |
| --- | --- |
| Trusted account ending **3821** | `GB46TEST00000000003821`, from [demo-account-3821.json](../payproof/fixtures/trusted_vendors/demo-account-3821.json), prior provenance reference `synthetic-onboarding/demo-account-3821` |
| Requested account ending **9928** | `GB57TEST00000000009928`, from [demo-account-change.json](../payproof/fixtures/requests/demo-account-change.json) |
| Exact new instruction | `Please pay this invoice to IBAN GB57TEST00000000009928.` |
| Reviewed result | `VERIFY` / `DESTINATION_CHANGED` |

The complete valid IBAN changes; vendor name, sender, bank label and currency match. The report explains the change and directs independent checking through the previously trusted callback. A legitimate update can produce this result. Full identifiers determine equality; suffixes are display aids.

Demo vendors, accounts and contacts are fictional. The demo always uses explicit **fixture extraction**, ignores live provider configuration/credentials, and captures fresh sources/evidence IDs/review IDs/comparison IDs and server timestamps. Expected fixture labels never determine runtime results.

For an unattended local smoke test:

```bash
make demo-smoke
```

This runs `demo --simulate-review`. Console output and the review operator ID explicitly identify a **synthetic source-review simulation**. The flag is accepted only for the fixed seeded demo, never file-based analysis. It creates no independent-verification event and makes no claim that a person called the vendor.

Pressing Enter, another word or EOF leaves `UNCERTAIN / REVIEW_REQUIRED`. To skip the prompt explicitly:

```bash
.venv/bin/python -m payproof demo --no-review
```

## Analyze local files

Select an already trusted vendor record explicitly. Its independent trust/provenance and callback must predate this request. PayProof validates record shape and chronology; it cannot establish that history or learn a baseline from the suspect request.

```bash
.venv/bin/python -m payproof analyze \
  --vendor trusted-vendor.json \
  --email payment-request.txt \
  --invoice invoice.txt \
  --operator local-reviewer
```

Omit either source for a single email/invoice, or use `--text request.txt`. Source flags may repeat. Limits remain 1–16 files, at most 20,000 total Unicode characters, bounded UTF-8 reads, and 64,000 bytes of strictly validated trusted-vendor JSON. Original text is preserved.

Arbitrary files and email/invoice pairs require the existing `live` extraction mode, provider key and explicit model in environment variables; see [EXTRACTION.md](EXTRACTION.md) and [.env.example](../.env.example). Only source documents go to the provider; the baseline and human review stay outside model input.

Default `disabled` extraction yields a canonical failure and `UNCERTAIN`. `fixture` mode recognizes only one exact bundled text/kind; it does not pretend to extract arbitrary text or pairs. Failed extraction skips the review prompt. Missing/unsupported destinations or conflicting instructions remain `UNCERTAIN` after review. A submitted verdict word such as `VERIFIED` neither acknowledges review nor sets a state.

`--no-review` also works for file analysis. `--operator` identifies the local actor acknowledging source review. Operating-system access controls this developer CLI; no web operator session is implemented here.

## Data flow and evidence

```text
selected trusted JSON -> strict baseline validation ------------------+
                                                                     |
email/invoice/text -> exact capture -> structured extraction           |
                                          |                          |
                              strict schema + quote validation       |
                                          |                          |
                           full source + all evidence displayed      |
                                          |                          |
                              explicit human source review           |
                                          |                          |
                              conservative normalization             |
                                          |                          |
                             deterministic comparison <--------------+
                                          |
                        state + reasons + differences + evidence IDs
                        + trusted callback for independent checking
```

[cases.py](../payproof/cases.py) owns `start_case`, `review_case` and `complete_case`. Review creates a source-bound snapshot with request/attempt bindings, operator, server time, and every displayed evidence ID. It normalizes all account observations, creating a reviewed identity only when every observation resolves to the same valid supported IBAN. It never chooses among distinct or invalid alternatives. The comparator does not manufacture a review.

[presentation.py](../payproof/presentation.py) shows the trusted revision, raw/canonical account, bank/routing/currency/email, prior source/provenance/time, and callback origin. Every source and extracted field includes its status, observed candidates, exact quotes, source ID/kind/label, evidence IDs and character/page locations. Missing fields remain missing. Untrusted text is JSON-escaped, including terminal escapes and Unicode direction controls; quoted strings decode to the exact original text.

Final state is only `UNCHANGED`, `VERIFY` or `UNCERTAIN`. Source review is distinct from independent vendor verification. The callback comes from the frozen baseline, never a request/reply-to field. This workflow creates no `VERIFIED` label or account-ownership assertion.

## Exit codes and limits

| Exit | Meaning |
| --- | --- |
| `0` | Reviewed supported comparison completed as `UNCHANGED` or `VERIFY`; neither grants permission to pay |
| `2` | `UNCERTAIN`, or invalid command-line usage; inspect the report/error |
| `1` | Local input, configuration, validation or chronology failed; no substitute decisive result is produced |

This slice runs in memory and creates no database or durable review/verification history. It displays the independent-checking action but does not record that action. The architecture's gated persistent web workflow, stale-revision checks, independent-verification command, restart survival and 36-case release gates remain next. GB/DE IBAN and plain text only; separate routing/other schemes remain unsupported. Live extraction integration uses mocked HTTP; no real API call was made.

## Verification

```bash
make verify
```

[test_vertical_slice.py](../tests/test_vertical_slice.py) covers the seeded capture-to-comparison path and CLI evidence display, all three outcomes, explicit/declined/EOF review, synthetic simulation isolation, email/invoice pairs through the real structured-output HTTP adapter with mocked responses, equivalent formatting/conflicting instructions, provider/evidence failures, malformed/recent baselines, bounds and terminal escaping. The wheel smoke test runs the seeded demo outside the repository and checks `3821` → `9928` yields `VERIFY`. No live network access is required.
