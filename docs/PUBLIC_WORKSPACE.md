# No-login public workspace

The browser landing page makes **VERIFY A PAYMENT REQUEST** the primary action. `/workspace` is a separately mounted Flask application reusing the existing backend workflow and validation. The optional Acme example is secondary and explicitly fixture-based. No provider is called by visiting the page or opening the example.

## Own-data workflow

A: choose a record already established in this temporary session, manually enter previously trusted information, or paste/upload previous evidence. Supported ingestion is UTF8 text and `.txt` / raw `.eml` files; no MIME attachments, PDF, MSG or OCR support is advertised. Capture produces the same immutable `SourceDocument` tuple used by extraction; later parsers can replace the capture boundary without changing review/comparison/receipt commands.

Previous evidence becomes an **untrusted draft**. Promotion requires explicit source review, prior-trust assertion and independent known-good contact assertion. Extraction cannot confer trust. The contact is entered separately by the human and retained in the trusted vendor record; current-request sender/reply-to cannot replace it.

B: enter the new payment request separately. Extraction → exact source/evidence validation → explicit source review → deterministic comparison → independent human check → receipt/history reuse the operator backend. Replacing evidence or retrying extraction clears downstream review/comparison/confirmation. Revising the vendor makes earlier cases and receipts stale. Receipts have an escaped HTML browser view and JSON API representation of human assertions, not signed ownership certificates or payment authorization.

## Isolation and retention

Anonymous sessions use a separate HttpOnly, SameSite=Strict cookie scoped to `/workspace` (Secure under production). A signed cookie plus a process-held random session registry controls access; IDs in forms/URLs cannot select another session's database. Each session has its own SQLite file in a generated directory under `PAYPROOF_DATA_DIR/public-sessions`. Public workspace routes never open the canonical operator database. Operator routes still require the separate private gate. The API key is server-only.

Sessions expire after 30 minutes of inactivity; logout or restart ends access. Inactive public directories are removed on subsequent session creation. This is opportunistic cleanup, not a guarantee of deletion at an exact deadline or from host backups. No durable recovery link or confidential enterprise storage is claimed. Maximum64 concurrent sessions and four new sessions/IP/minute limit churn. Host administrators remain trusted. Run one worker as in the current production command; session/IP rate registries are process-local. The global extraction budget is durable across workers/restarts.

Use **synthetic/test data only** in the public hackathon experience. This is not authentication, organizational tenant management or real-pilot readiness.

## Live extraction and cost controls

Public live AI is **off by default**, independently of the private operator mode. Configure privately:

```
PAYPROOF_EXTRACTION_MODE=live
PAYPROOF_PUBLIC_LIVE_ENABLED=true
PAYPROOF_PUBLIC_LIVE_MAX_CALLS=20
```

Key/provider/model remain in the existing server/private configuration. The selected model currently has no successful live proof: the prior Featherless tests returned HTTP403. Do not advertise successful live analysis until a real grounded request succeeds.

Public live extraction requires explicit enablement and valid live configuration. Limits: existing six extraction attempts/session/minute, three live attempts/IP/minute, plus a **global lifetime ceiling** of1–100 reserved attempts (default20). The budget lives in `public-live-budget.sqlite3`, outside session directories; clearing cookies or restarting does not replenish it. Every reserved attempt counts, including failures and requests later rejected by validation. Input/response/token limits still apply. Duplicate persisted case submissions are resolved before another provider reservation. There is no anonymous quota reset endpoint.

This bounds anonymous provider invocations, not an exact dollar budget. Model/context pricing is unknown; an attacker can still exhaust the shared allowance and disrupt availability. The owner must control provider credits and intentionally adjust the cap if more calls are wanted. Do not delete/reset the ledger casually or expose unrestricted public live access.

With live disabled, arbitrary source extraction returns an explicit NOT_CONFIGURED failure; the source/history remains visible but no decisive state or confirmation is invented. Fixture mode never masquerades as live and no live error falls back to fixture observations.

## Verification

Integration tests use real mounted Flask routes and real SQLite stores. Provider success/timeout responses are mocked. Tests cover own manual baseline → new destination → review → VERIFY → human action → receipt; two-client case/draft/receipt isolation; no operator-record access; CSRF/logout; disabled live/no provider calls; explicit sample; and budget persistence across restart. These are not live model accuracy or browser usability measurements.

Liveness: `/healthz`. `/readyz` checks local storage/configuration only and explicitly reports provider connectivity NOT_CHECKED. Public usability does not require operator login credentials. Production still requires a private signing secret and HTTPS.

No deployment or external pilot was performed by this change. Existing gold failures remain visible; frozen benchmark labels/scoring are unchanged.

Current local verification: the full suite and mounted routes pass with mocked provider responses; production package smoke includes no-login landing/forms/assets outside the checkout. Actual public hosting/HTTPS and a successful Featherless run remain unverified. Browser/mobile usability has not been manually certified.

Final checks:785 tests passed; lint, formatting, strict typecheck, build, installed package smoke and synthetic loopback Gunicorn HTTP/health PASS. Gold remains FAIL (56/72 held-out states,53/72 exact; diagnostic28/30), with0 critical false UNCHANGED in gold. Frozen evaluation protocol PASS. Live was not rerun, and no public deployment occurred. Machine-readable gate summary: `PUBLIC_WORKSPACE_VERIFICATION.json`. Isolation/provider tests are mocked/synthetic, not real model or security certification.
