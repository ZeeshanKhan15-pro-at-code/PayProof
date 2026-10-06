# Phase-2 live benchmark results

Status on 2026-10-06: **BLOCKED — NOT_CONFIGURED**.

The process environment does not contain nonblank `PAYPROOF_EXTRACTION_MODE`, `PAYPROOF_PROVIDER_API_KEY` or `PAYPROOF_PROVIDER_MODEL`. Environment parsing therefore selects disabled extraction, with no provider credential or model. The application reads these settings from the process environment only; editing `.env.example` does not configure a live process. No credential file or Git history was used to supply a key.

The frozen held-out corpus and protocol hashes validate successfully: 72 cases. The live command was attempted:

```bash
.venv/bin/python -m payproof.heldout_benchmark --live --output benchmarks/phase2-runs/before-2026-10-06
```

It exited **2** before extraction with the sanitized diagnostic:

```text
Held-out input/configuration failed: ValueError; no passing result claimed.
```

| Observation | Actual outcome |
| --- | --- |
| Planned held-out cases | 72 |
| Provider requests | 0 |
| Completed live case evaluations | 0 |
| BEFORE predictions/results | NOT_RUN; no output directory created |
| AFTER predictions/results | NOT_RUN |
| Field extraction / evidence / schema metrics | NOT_MEASURED |
| Change recall / critical false UNCHANGED / false VERIFY | NOT_MEASURED |
| Correct UNCERTAIN / end-to-end accuracy | NOT_MEASURED |
| Extraction versus comparison failures | NOT_MEASURED |

This is an environment-readiness blocker, not a provider rejection, extraction defect, comparator failure or evidence that the system passed. There are no live failures to classify, no P0 miss assessment, no implementation fixes and no BEFORE/AFTER performance claim. Fixture, mock and gold-comparison results were not substituted. Labels, grounding rules, extraction contracts and deterministic semantics remain unchanged.

To unblock, configure `PAYPROOF_EXTRACTION_MODE=live`, a provider key and an explicit model privately in the environment inherited by the benchmark process, then rerun the command above. Do not put a key into a tracked template, a command argument, a results artifact or this document. Provider access and network connectivity have not been tested by this attempt. Preserve the first real run before diagnosing or fixing implementation failures.
