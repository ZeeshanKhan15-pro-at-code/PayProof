# Minimal PayProof operator web workflow

The Flask `/operator` pages implement the existing SQLite commands; extraction, source grounding, normalization, comparison, stale-revision checks and human-event contracts remain in their existing modules. No decision logic is duplicated in templates. There is no payment operation or global approval status.

## Configuration and startup

Set configuration in the launching environment; `.env` is not loaded automatically. Do not put real secrets in `.env.example`, source, URLs or Git.

- `PAYPROOF_SECRET_KEY`: random session-signing secret, at least 32 characters.
- `PAYPROOF_OPERATOR_TOKEN`: separate random operator passphrase, at least 32 characters; distinct from signing and provider credentials. Login posts it as a password and never retains it in the cookie, database or logs.
- `PAYPROOF_DATA_DIR`: private persistent local directory, default `data/`.
- `PAYPROOF_EXTRACTION_MODE`: `fixture` for the reproducible synthetic demonstration; `live` requires the existing environment-only provider key/model configuration; `disabled` records an explicit unsuccessful extraction.
- `PAYPROOF_ENV=production`: requires a signing secret and sets Secure cookies. Use a restricted HTTPS endpoint; local development uses loopback HTTP without Secure cookies.

```bash
make serve
# Open http://127.0.0.1:8000/operator
# A configured production host may instead run:
make production
```

The operator workflow returns 503 while the passphrase is unconfigured. App initialization/health checks do not initialize a database or call a provider. Authenticated workflow access initializes schema v1 on first storage use. The browser `/` entry redirects to `/operator`; health and default JSON capability requests remain available without exposing evidence. Public health is liveness only.

## Seeded synthetic demonstration

1. Log in with the configured operator passphrase and an attribution label.
2. Click **Add seeded synthetic vendor (account ending 3821)**. This stores the bundled fictional onboarding record and callback `+1-202-555-0182`.
3. Open **Open seeded synthetic email case**; the seeded vendor and exact email are populated for inspection. Alternatively use **Create a case and run extraction** and select Synthetic PayProof Demo Supplies.
4. Inspect the populated **Email text**, or copy the exact text from the expanded example. It requests `GB57TEST00000000009928`; the prior record contains `GB46TEST00000000003821`.
5. Create the case. In explicitly configured fixture mode, extraction is labeled **FIXTURE**, not AI/live accuracy. Other text does not receive invented fixture observations; live mode never falls back to fixtures.
6. Inspect every original source, exact span and the independent destination inventory. Check the unselected source-review acknowledgement and submit **Acknowledge source review only**.
7. Click **Run deterministic comparison**. Expect `VERIFY`, `DESTINATION_CHANGED`, full trusted/new identifiers and their origins, and the previously trusted contact.
8. For a synthetic human-check demonstration only, report the simulated person/role in the independent-check section, explicitly choose an outcome, and check the separate independent-check attestation. Label simulation in notes. A confirmed outcome produces a human record and derives `VERIFIED`; the comparison remains `VERIFY`.
9. Inspect all retained versions and independent-check outcomes. Restarting Flask preserves the records in SQLite.

The seeded callback is fictional; this procedure demonstrates human-event recording, not an actual call. There is no simulated checkbox that automatically confirms a record, no automatic source review and no automatic verification.

## Safety and failure behavior

The page separates three numbered sections: source review, deterministic comparison and independent human verification. A persistent banner says payment authorization is not provided. Source review acknowledges inspection only. Comparison displays one of the three canonical states with plain-language reasons, field differences, missing information and contradictions. `UNCHANGED` means destination equality only. A changed destination requires independent checking. An unresolved case explains its reason codes and cannot be confirmed.

Original sources and inventory context remain fully visible; extraction status, method/model/failure, candidate values, exact quotes, source IDs and offsets are shown. Prior trusted account provenance and callback provenance come from the frozen vendor baseline. Request text is labeled untrusted; any claims appearing inside it are preserved as evidence, never adopted as application conclusions. Templates do not use `safe` or render provider verdicts.

Every write requires a signed operator session, an unpredictable per-session CSRF token and same-origin validation of supplied Origin/Referer headers. Sessions expire after 30 minutes of inactivity. A bounded process-local registry revokes the session on logout; restarting the app (including after passphrase rotation) invalidates old signed cookies. Each restart requires a fresh login, and the one-worker deployment is required. Forms reject duplicate/unknown fields. Human identity comes from the session; posted state, callback, operator or confirmation overrides are rejected. The server supplies timestamps and the stored exact identity/contact. Checkboxes are unselected; outcome selection has an empty placeholder and no default confirmation.

Writes bind the displayed expected case revision. Trusted-record, source, review, comparison or engine changes invalidate eligibility; stale pages show an explicit warning beside historical comparison results. Refresh clears the current review/comparison/attestation and requires inspection/comparison again. Old human records remain historical, never current by implication. Repeated independent action IDs obey backend idempotency. Negative and inconclusive checks remain visible without deriving `VERIFIED`.

Extraction failures (including missing configuration, timeout, provider/schema/grounding failures) are saved as unsuccessful attempts with sources intact. Successful source review is blocked, comparison abstains, and independent confirmation is blocked. Invalid inputs, unacknowledged actions, stale writes and storage failures return sanitized errors without echoing validator/provider/SQL payloads or claiming success. To retry extraction or correct unsupported input in this minimal interface, create a new case; the CLI retains its existing correction workflow.

## Boundaries and limits

UTF-8 pasted email/invoice/vendor-notice/plain text and `.txt`/`.eml` uploads are supported. No PDF, OCR, archives, remote links or attachments are processed. Aggregate text is bounded by the existing 20,000-character/16-source contract; Flask also limits the HTTP body to 100,000 bytes. Oversized/invalid inputs are rejected, never truncated. Pasted browser form CRLF line endings are captured as LF before hashing/extraction; other text is preserved, and uploaded UTF-8 file contents are not normalized. Every evidence span is validated against that frozen capture. Upload filenames are not trusted metadata and files are not saved separately. Literal currently configured secrets accidentally pasted into sources, vendor data or human notes are rejected by scanning actual values before extraction/rendering/storage, including archived data loaded for display. Encoded or unknown historical secrets are not comprehensively recognized. A contaminated private archive may require separate recovery rather than display.

One shared passphrase gates the single-operator prototype; labels provide attribution, not individual authentication. No registration, role model or password recovery is introduced. Host administrators and the private volume remain trusted. Keep Gunicorn on loopback behind restricted HTTPS; do not expose financial records publicly. Cookies are HttpOnly/SameSite Strict, and Secure in production. Evidence pages are `no-store`; CSP prevents scripts, framing and cross-origin form submission. Static CSS contains no data. Burst limits are in-memory/per-process (five login attempts per IP/minute, six extraction attempts per session/minute), not distributed or durable quotas; use the existing one-worker deployment.

The index shows the most recent 50 cases. Every case retains its own full version history. The UI deliberately has no baseline replacement, evidence editing, case deletion, payment, banking integration, account-ownership claim or autonomous approval feature. Prior-trust entry is a human assertion and cannot prove the historical source was trustworthy. Lexical inventory and model extraction retain their documented incompleteness risks.

## Validation

`tests/test_operator_web.py` exercises the 3821→9928 sequence, restart persistence, strict prior-trust entry, comparison without review, unchanged/missing/unsupported destinations, source escaping, upload/body limits, forged states/contacts, negative outcomes, stale-case/vendor changes, authentication, CSRF, origin, cancellation-by-missing-acknowledgement and mocked live failures/omissions. Mocked and fixture tests make no live model or contact calls and are not extraction benchmark results.

```bash
make lint
make typecheck
make test
make build
```

The wheel includes templates, CSS and SQL. Installed-package validation exercises the operator login page and authenticated vendor/case page so checkout-only asset availability cannot mask packaging failures.

Actual checkout verification: lint/typecheck passed, installed wheel migration/restart and authenticated pages/assets passed, and the synthetic Flask integration sequence preserved `VERIFY` alongside a separate human confirmation. A separate actual-loopback Gunicorn smoke attempt was **BLOCKED** at `socket.socket()` by `PermissionError: [Errno 1] Operation not permitted` in this execution sandbox; no listener or external browser result is claimed. This is an infrastructure restriction, not a failed Flask request test. To check listener health on an unrestricted local host, run `make serve` and request `http://127.0.0.1:8000/healthz`; the installed production health check is reproducible with `.venv/bin/python scripts/check_wheel.py --http` after `make build`.
