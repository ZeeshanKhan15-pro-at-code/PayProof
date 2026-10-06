"""Validate a frozen held-out corpus; evaluate only through explicit commands."""

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from payproof.benchmark_harness import RunReport, render_summary, run_benchmark
from payproof.benchmark_scoring import summarize
from payproof.config import ConfigurationError, load_settings
from payproof.evaluation_contracts import BenchmarkDataset, HeldOutCorpus
from payproof.schemas import EVIDENCE_FIELDS
from payproof.validation import parse_contract

DEFAULT_ROOT = Path("benchmarks/phase2-heldout-v1")
FROZEN_FILES = ("authoring.json", "cases.json", "schema.json")
PROTOCOL_FILES = (
    "docs/PHASE2_BENCHMARK_SPEC.md",
    "payproof/heldout_benchmark.py",
    "payproof/benchmark_scoring.py",
    "payproof/benchmark_harness.py",
    "payproof/evaluation_contracts.py",
    "scripts/compile_heldout.py",
)


def load_frozen(root: Path) -> HeldOutCorpus:
    manifest = json.loads((root / "freeze.json").read_text())
    if (
        set(manifest["sha256"]) != set(FROZEN_FILES)
        or manifest["prediction_execution"] != "NOT_RUN_AT_FREEZE"
        or manifest["label_origin"] != "AUTHOR_SPECIFIED_BEFORE_EXECUTION_NO_MODEL"
    ):
        raise ValueError("Invalid pre-execution freeze")
    for name in FROZEN_FILES:
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != manifest["sha256"][name]:
            raise ValueError("Frozen definition hash mismatch; do not silently relabel")
    if set(manifest["protocol_sha256"]) != set(PROTOCOL_FILES):
        raise ValueError("Frozen protocol file set differs")
    repo = Path(__file__).resolve().parents[1]
    for name in PROTOCOL_FILES:
        if (
            hashlib.sha256((repo / name).read_bytes()).hexdigest()
            != manifest["protocol_sha256"][name]
        ):
            raise ValueError(
                "Frozen evaluation protocol changed; do not alter scoring after execution"
            )
    corpus = parse_contract(HeldOutCorpus, (root / "cases.json").read_bytes())
    if json.loads((root / "schema.json").read_text()) != HeldOutCorpus.model_json_schema():
        raise ValueError("Frozen schema differs from installed evaluation contract")
    return corpus


def fraction(numerator: int, denominator: int) -> dict[str, int | None]:
    return {"numerator": numerator if denominator else None, "denominator": denominator}


def extended_metrics(report: RunReport, corpus: BenchmarkDataset) -> dict[str, Any]:
    """Integer counts, no invented zeros for unevaluated extraction diagnostics."""
    pipeline = next((t for t in report.tracks if t.track == "conditional_pipeline"), None)
    if pipeline is None:
        return {"status": "NOT_RUN", "extraction_metrics": None}
    metrics = pipeline.metrics
    by_id = {a.case_id: a for a in report.extraction_attempts}
    schema = Counter(a.wire_schema_status for a in report.extraction_attempts)
    accepted_spans = rejected_grounding = failed = 0
    grounding_cases = 0
    for outcome in pipeline.outcomes:
        attempt = by_id[outcome.case_id]
        evidence = attempt.evidence
        if evidence is not None and evidence.extraction.failure_code == "EVIDENCE_INVALID":
            rejected_grounding += 1
        if outcome.failed_operation:
            failed += 1
        elif evidence is not None:
            # evaluate_case already validated exact source/quote/location contracts.
            grounding_cases += 1
            accepted_spans += len(evidence.spans())
    expected_fields = {
        name: sum(
            len({c.value for c in getattr(case.gold_evidence, name).candidates})
            for case in corpus.cases
        )
        for name in EVIDENCE_FIELDS
    }
    fields = {
        name: {
            "value_precision": fraction(f["correct_values"], f["observed_values"]),
            "value_recall": fraction(f["correct_values"], expected_fields[name]),
            "status_accuracy": fraction(f["status_correct"], f["cases"]),
        }
        for name in EVIDENCE_FIELDS
        for f in [
            metrics.fields.get(
                name, {"correct_values": 0, "observed_values": 0, "status_correct": 0, "cases": 0}
            )
        ]
    }
    # Failures supply no correct fields; keep the full planned case denominator.
    exact_fields = {
        name: fraction(
            sum(
                f.status_correct and f.correct_values == f.expected_values == f.observed_values
                for o in pipeline.outcomes
                for f in o.field_scores
                if f.field == name
            ),
            metrics.total_cases,
        )
        for name in EVIDENCE_FIELDS
    }
    role_correct = sum(f.correct_values for o in pipeline.outcomes for f in o.field_scores)
    role_observed = sum(f.observed_values for o in pipeline.outcomes for f in o.field_scores)
    full_status = {
        name: fraction(metrics.fields.get(name, {}).get("status_correct", 0), metrics.total_cases)
        for name in EVIDENCE_FIELDS
    }
    false_verify = [
        o.case_id
        for o in pipeline.outcomes
        if not o.failed_operation
        and o.result is not None
        and o.result.state == "VERIFY"
        and o.expected.state != "VERIFY"
    ]
    strata = {}
    for family in sorted({c.tags[0] for c in corpus.cases}):
        cases = tuple(c for c in corpus.cases if c.tags[0] == family)
        ids = {c.case_id for c in cases}
        outcomes = tuple(o for o in pipeline.outcomes if o.case_id in ids)
        strata[family] = summarize(cases, outcomes).model_dump(mode="json")
    return dict(
        status="MEASURED",
        family_strata=strata,
        total_cases=metrics.total_cases,
        end_to_end_state_accuracy=fraction(
            metrics.correct_state_classifications, metrics.total_cases
        ),
        consequential_change_recall=fraction(
            metrics.consequential_changes_detected, metrics.consequential_changes
        ),
        supported_change_recall=fraction(
            metrics.supported_changes_detected, metrics.supported_consequential_changes
        ),
        critical_false_UNCHANGED=metrics.critical_false_unchanged,
        critical_case_ids=metrics.critical_miss_case_ids,
        unsafe_false_UNCHANGED_case_ids=[
            o.case_id
            for o in pipeline.outcomes
            if not o.failed_operation
            and o.result is not None
            and o.result.state == "UNCHANGED"
            and o.expected.state != "UNCHANGED"
        ],
        false_VERIFY_count=len(false_verify),
        false_VERIFY_case_ids=false_verify,
        correct_UNCERTAIN=fraction(
            metrics.uncertain_cases_handled_correctly, metrics.expected_uncertain_cases
        ),
        extraction_error_cases=metrics.extraction_error_cases,
        extraction_failed_cases=failed,
        comparison_error_cases=metrics.deterministic_comparison_failures,
        field_accuracy=fields,
        full_attempt_exact_field_accuracy=exact_fields,
        field_role_grounding_precision=fraction(role_correct, role_observed),
        full_attempt_field_status_accuracy=full_status,
        exact_evidence_valid_spans=accepted_spans,
        exact_evidence_assessed_spans=accepted_spans,
        grounded_success_cases=fraction(grounding_cases, metrics.total_cases),
        rejected_evidence_payloads=rejected_grounding,
        schema_failure_rate=fraction(schema["FAIL"], schema["PASS"] + schema["FAIL"]),
        schema_pass_count=schema["PASS"],
        schema_fail_count=schema["FAIL"],
        schema_unassessable_count=schema["UNAVAILABLE"],
        all_safe_extraction_failures=metrics.extraction_failures,
        categories=metrics.error_categories,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Frozen held-out definition validation / evaluation"
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--evaluate-gold", action="store_true")
    modes.add_argument("--live", action="store_true")
    modes.add_argument("--replay", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        corpus = load_frozen(args.root)
        if not (args.evaluate_gold or args.live or args.replay):
            print(
                f"PASS: {len(corpus.cases)} frozen definitions; predictions NOT_RUN; label review PENDING"
            )
            return 0
        if args.output is None or args.output.exists():
            raise ValueError("Evaluation requires a new output directory; preserve prior runs")
        if args.output.resolve().is_relative_to(args.root.resolve()):
            raise ValueError("Store observations outside the frozen dataset directory")
        settings = load_settings(os.environ) if args.live else None
        if settings is not None and settings.extraction_mode != "live":
            raise ValueError("Held-out live evaluation forbids fixture/disabled modes")
        report = run_benchmark(
            args.root / "cases.json",
            settings=settings,
            replay_path=args.replay,
            corpus_model=HeldOutCorpus,
        )
        # Check definitions still frozen after prediction; no silent concurrent changes.
        load_frozen(args.root)
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "report.json").write_text(report.model_dump_json(indent=2) + "\n")
        metrics = extended_metrics(report, corpus)
        (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
        summary = (
            render_summary(report)
            + "\nHeld-out supplemental metrics:\n"
            + json.dumps(metrics, indent=2)
            + "\n"
        )
        (args.output / "summary.txt").write_text(summary)
        print(summary, end="")
        return 0 if report.passed else 1
    except (ConfigurationError, ValidationError, ValueError, OSError, KeyError, TypeError) as error:
        print(
            f"Held-out input/configuration failed: {type(error).__name__}; no passing result claimed.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
