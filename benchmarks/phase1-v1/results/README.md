# Recorded Phase-1 diagnostic results

These are measured automatic runs of the frozen 30-case public diagnostic corpus, not held-out results. Independent label review is still `PENDING`. The immutable corpus SHA-256 is `3bc6dcafaeb661b00cf22fd06fc86802c8db642c41d9228676faae3b546a0c7f`; no case, gold label, or normalization policy was changed to obtain these results.

## Gold comparison

See [summary.txt](gold/summary.txt) and [report.json](gold/report.json).

| Metric | Measured result |
| --- | --- |
| Total cases | 30 |
| Correct state classifications | 30/30 |
| Exact state/reason/value/evidence agreement | 30/30 |
| Known consequential changes | 13 |
| Changes detected as correct VERIFY | 10 |
| Changes not detected as VERIFY | 3 |
| Supported changes detected | 10/10 |
| Known changes handled by abstention | 3 |
| Critical misses (false UNCHANGED proxy) | 0 |
| Unchanged incorrectly escalated as VERIFY | 0 |
| Expected uncertainty correctly handled | 13/13 |
| Deterministic-comparison failures | 0 |

The three abstentions are PP-07 (separate routing), PP-08 (account plus separate routing), and PP-29 (unsupported country). They are counted as **not detected**, even though their `UNCERTAIN` outcomes match the frozen policy. They are not false `UNCHANGED` results. The separate gold review-gate run also passed 30/30; it establishes that unreviewed observations stay unresolved, not change-detection accuracy.

Gold input and review are synthetic. No model extracted those gold observations, no operator read the sources during these runs, and no independent callback or bank ownership verification occurred. UI/action enforcement is `NOT_EVALUATED`.

## Configured extraction failure

See [summary.txt](extraction/summary.txt) and [report.json](extraction/report.json).

The actual execution environment had extraction disabled with no provider key/model configured. All 30 source attempts returned `NOT_CONFIGURED`. The conditional pipeline therefore records 30 extraction failures, zero successful classifications, zero detected changes, and zero comparison failures. All 13 known changes were not detected in this track. The same 30 attempts feed the extraction review-gate track; they are not 60 independent provider attempts.

These outcomes are operation failures, not 13 correctly handled uncertain cases or evidence of AI accuracy. The comparator produced fail-safe `UNCERTAIN` results, and there were no false `UNCHANGED` results, but the failed extraction track does not pass the acceptance target. No provider call, provider cost estimate, or fabricated live response is reported.

Root cause is missing live extraction configuration, not a normalization/comparison defect. Configure `PAYPROOF_EXTRACTION_MODE=live`, `PAYPROOF_PROVIDER_API_KEY`, and `PAYPROOF_PROVIDER_MODEL` through the existing environment mechanism, then rerun `make benchmark-extraction`. Keep keys out of source and chat. No prompt/comparator optimization or case-specific fallback was used. Existing fixtures are never substituted for these failed attempts.

## Reproduction and provenance

```bash
make benchmark
make benchmark-extraction
.venv/bin/python -m payproof benchmark --replay benchmarks/phase1-v1/results/extraction/report.json
```

The first command passes the gold tracks. The extraction and replay CLI return 1 for the recorded disabled-configuration run; Make reports its failed recipe with a nonzero exit status. Reports retain every case and original extraction attempt, ordered reasons, values, evidence, error categories, confusion counts, exact integer fractions, hashes, originating Git commit, dirty-worktree metadata, and Python version. A zero fraction denominator means undefined, not zero accuracy. Attempt timings are measured separately; they are not provider latency measurements for this disabled run.

Replaying the recorded observations uses no network and reproduces the scoring digest. Fresh live extraction may vary; its predictions must be stored and reported separately. A pre-commit dirty tree is explicitly recorded because the harness executed before the commit containing this implementation/output; source-file hashes identify the exact implementation. The design corpus retains `NOT_RUN` as authoring metadata, with measured outcomes exclusively in these run reports.

The harness regression tests inject failures to verify case IDs, stage attribution, wrong-role critical misses, missing evidence despite correct enums, permitted equivalent quotes/deduplication, context-only errors, and replay integrity. Those stubs are test results, not measured live benchmark outputs. The independently reviewed 36-case release corpus, held-out extraction runs, and real human-workflow evaluation remain incomplete.
