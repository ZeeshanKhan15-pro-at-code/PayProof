# Verification result and receipt

The shared server-rendered result page serves both the isolated no-login workspace and the private operator workflow. It leads with the persisted comparison finding, not an extraction verdict. Comparison, extraction contracts, instruction inventory, benchmark labels and human-command authority are unchanged.

## Read the finding first

- **VERIFY — PAYMENT DESTINATION CHANGED.** Previously trusted and requested endings appear side by side, with independent verification required and machine-readable reasons. Full supported identifiers, not account tails, determine equality.
- **UNCHANGED — NO SUPPORTED PAYMENT DESTINATION CHANGE DETECTED.** Immediately qualified by “This does not authorize payment or prove the request is legitimate.”
- **UNCERTAIN — PAYPROOF CANNOT RELIABLY COMPARE THIS REQUEST YET.** Exact reason codes, their explanations, missing fields, contradictions and extraction failure codes remain visible. The page does not select an account when comparison has no established requested identity.
- **Pending:** no comparison state has been assigned. **Stale:** the historical warning supersedes the old finding; review/comparison are labeled historical and new confirmation controls are unavailable.

Four separate responsibility cards identify source review, payment comparison, independent human verification and payment authorization outside PayProof. No result or receipt authorizes a payment. `VERIFIED` remains a separately derived human attestation, never an extraction/comparison state.

## Follow the source

Original source → AI observation (or explicitly labeled fixture observation) → reviewed evidence → deterministic comparison → verification requirement → human action.

Account observations lead with exact excerpts and linked original-source IDs/character offsets. The independently generated source inventory exposes competing regions, contextual hints and values omitted by extraction. Historical/current hints do not prove intent. All original source text stays available; other extracted fields retain exact spans and source references. Jinja autoescaping applies to source text, values, notes and history.

VERIFY shows the callback from the recorded trusted vendor baseline, its provenance, and the exact requested destination to check. It explicitly warns against contacts supplied only by the new request. No callback, contact identity or bank ownership is independently authenticated by PayProof.

## Receipt integrity and print

The HTML/JSON receipt is bound to the immutable **source case revision of the recorded independent-check event**, rather than the newest case/vendor data. Storage checks the recorded comparison ID, baseline revision, trusted contact and checked identity against the event before serving the receipt. A mismatch fails closed.

The receipt includes vendor/case, full trusted/requested comparison values, reasons, exact extracted evidence, independently retained source context, source register/hashes, method/provider/model, review/check timestamps, human outcome/notes and case/vendor/contact/comparison/extraction/event revisions. Each receipt states that payment authorization and account ownership are not provided/established and that it does not establish legitimacy, fraud or payment approval.

Current/stale status is computed on request. A stale receipt preserves the old values and clearly says HISTORICAL — NOT CURRENT, even if the latest comparison is now UNCHANGED. Printed copies show their generation time and cannot update after later edits. They are human assertion records, not signed certificates.

The browser Print receipt button calls only `window.print()` from a packaged same-origin external script. CSP permits same-origin scripts but no inline scripts/eval. Print CSS removes navigation/buttons, retains evidence, source references/digests, comparison and revisions, wraps long values, and avoids splitting small evidence blocks. Entire original documents remain expandable online; print includes exact excerpts/context rather than duplicating every full source. No server-side PDF generation or PDF ingestion is added.

## Executable evidence and limits — 2026-10-09

`tests/test_verification_ux.py` adds ten integration regressions using real Flask/SQLite paths and synthetic fixture observations: all three findings, missing/provider-disabled evidence, historical/current omission visibility, three human outcomes, print controls/assets, stale receipt preservation and mismatch rejection. Existing public isolation, human-state integrity and escaped-content tests also run.

The final complete verification run passed lint, formatting, strict typecheck, **795 tests**, configuration, frozen protocol, build and installed-wheel smoke. Gold diagnostic remains **28/30 states**, held-out gold **56/72 states and 53/72 exact**, both FAIL; critical false UNCHANGED remains **0** in both gold tracks. These are GOLD/SYNTHETIC comparisons, not live model accuracy. Frozen evidence and labels were preserved. Final evidence is saved at `/tmp/payproof-verification-ux-release-20261009/gates.json`, with benchmark reports in its `diagnostic/` and `heldout/` directories and command output in `/tmp/payproof-verification-ux-release-20261009.log`. The verification command below produces fresh independent artifacts and continues after failed benchmark gates. The print script is allowed only on receipt endpoints; other pages retain the prior no-script policy.

Chrome visibly rendered the synthetic changed-destination result and trusted callback/action section using a temporary loopback server. The receipt request returned HTTP200, but Chrome reported `ERR_BLOCKED_BY_CLIENT` on two attempts. Its cause is unknown; browser protections were not disabled. HTML/JSON receipt integration and packaged print assets pass, but actual browser print-preview/page-break inspection is **BLOCKED in that browser**, not claimed successful. Mobile layout and accessibility are not certified. The roughly 15-second comprehension target is a design goal, not a measured human usability result.

No live provider request, public deployment or real independent callback occurred. The browser test recorded an explicitly labeled simulated INCONCLUSIVE outcome on disposable synthetic data; it did not create VERIFIED. Existing successful live extraction uncertainty remains outside this UI change.

```bash
# Offline synthetic verification; preserves failures and builds package/assets.
.venv/bin/python scripts/verify_foundation.py /tmp/payproof-ux-verification-new-run
# Targeted result/receipt regressions:
.venv/bin/python -m pytest -q tests/test_verification_ux.py tests/test_public_workspace.py
# Local run uses the existing ignored private configuration:
make serve
```

For manual validation: open the secondary Acme example, inspect and acknowledge all sources, compare, and confirm the 3821 → 9928 finding, excerpt and previously trusted callback. Use only a deliberately simulated action for demo receipt testing; real confirmation requires the independent human check. Open the receipt and use Print receipt/Ctrl or Cmd+P. Check the source register, revisions, boundaries and page wrapping. Test missing/conflicting sources separately and confirm UNCERTAIN has no confirmation form.
