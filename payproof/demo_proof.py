"""Reproducible synthetic mechanism proof and artifact-backed evaluation report.

This is a demonstration runner, not an extractor or benchmark scoring engine.
It never contacts a provider or creates an independent-verification event.
"""

import argparse
import hashlib
import os
from html import escape
from importlib.resources import files
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from payproof.benchmark_harness import RunReport
from payproof.cases import complete_case, review_case
from payproof.config import Settings, load_settings
from payproof.extraction import extract_documents
from payproof.presentation import render_evidence, render_result
from payproof.schemas import (
    CaseContract,
    ComparisonState,
    Contract,
    ReasonCode,
    TrustedVendorRecord,
)
from payproof.secret_guard import reject_configured_secrets
from payproof.storage import SQLiteStore
from payproof.validation import parse_contract
from payproof.workflow_contracts import CaseInputs

DEFAULT_GOLD = Path("benchmarks/phase2-redteam/after-gold/report.json")
DEFAULT_LIVE = Path("benchmarks/phase2-redteam/live-attempt.json")


class DemoCase(Contract):
    case_id: str
    title: str
    inputs: CaseInputs
    expected_state: ComparisonState
    required_reasons: tuple[ReasonCode, ...] = Field(min_length=1)


class DemoBundle(Contract):
    dataset: Literal["SYNTHETIC_DEMO_PROOF_V1"]
    vendor: TrustedVendorRecord
    cases: tuple[DemoCase, ...] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def grounded_inputs(self) -> "DemoBundle":
        if len({c.case_id for c in self.cases}) != len(self.cases):
            raise ValueError("demo IDs must be unique")
        for case in self.cases:
            CaseContract(**case.inputs.model_dump(), baseline=self.vendor)
            if case.inputs.evidence.extraction.method not in ("FIXTURE", "NOT_ATTEMPTED"):
                raise ValueError("demo observations must not impersonate live extraction")
        return self


class BlockedLiveAttempt(Contract):
    """Saved no-call attempt, explicitly not a completed benchmark run."""

    date: str
    status: Literal["BLOCKED"]
    reason: Literal["NOT_CONFIGURED"]
    command: str
    exit_code: Literal[2]
    extraction_mode: Literal["disabled"]
    provider_key_available: Literal[False]
    provider_model_configured: Literal[False]
    provider_calls: Literal[0]
    completed_live_cases: Literal[0]
    planned_cases: int = Field(ge=1)
    live_metrics: Literal["NOT_MEASURED"]
    diagnostic: str


class ProofArtifact(Contract):
    artifact_version: Literal["payproof-demo-proof-v1"] = "payproof-demo-proof-v1"
    review_protocol: Literal["SIMULATED_DEMO_SOURCE_REVIEW"] = "SIMULATED_DEMO_SOURCE_REVIEW"
    bundle: DemoBundle
    outcomes: tuple[CaseContract, ...]
    gold_path: str
    gold_sha256: str
    gold: RunReport
    live_status_path: str
    live_status_sha256: str
    live_status: BlockedLiveAttempt

    @model_validator(mode="after")
    def separate_tracks(self) -> "ProofArtifact":
        if self.gold.extraction_status != "NOT_RUN" or self.gold.extraction_attempts:
            raise ValueError("gold report must not contain extraction predictions")
        if {t.track for t in self.gold.tracks} != {"gold_comparison", "gold_review_gate"}:
            raise ValueError("expected separate gold comparison and review gate tracks")
        for track in self.gold.tracks:
            metrics = track.metrics
            if (
                metrics.total_cases != len(track.outcomes)
                or metrics.correct_state_classifications
                != sum(o.state_correct for o in track.outcomes)
                or metrics.exact_correct_cases != sum(o.exact_correct for o in track.outcomes)
                or metrics.extraction_failures is not None
                or self.live_status.planned_cases != metrics.total_cases
            ):
                raise ValueError("saved metrics and outcomes disagree")
        if len(self.outcomes) != len(self.bundle.cases):
            raise ValueError("every demo must retain its outcome")
        for item, outcome in zip(self.bundle.cases, self.outcomes, strict=True):
            if (
                outcome.sources != item.inputs.sources
                or outcome.baseline != self.bundle.vendor
                or outcome.evidence.request_id != item.inputs.evidence.request_id
                or outcome.verification is not None
                or outcome.comparison is None
                or outcome.review is not None
                and outcome.review.operator_id != self.review_protocol
            ):
                raise ValueError("demo output binding or simulation attribution invalid")
        return self


def load_demo() -> DemoBundle:
    return parse_contract(
        DemoBundle, files("payproof").joinpath("fixtures/demo_proof/acme.json").read_bytes()
    )


def prepared_inputs(item: DemoCase) -> CaseInputs:
    if item.inputs.evidence.extraction.failure_code:
        # Exercise the real disabled-extraction failure path, with no credentials,
        # network call, fallback or implication that a provider was tested live.
        return CaseInputs(
            sources=item.inputs.sources,
            evidence=extract_documents(
                item.inputs.sources,
                settings=Settings(extraction_mode="disabled"),
                request_id=item.inputs.evidence.request_id,
            ),
        )
    return item.inputs


def run_demo(bundle: DemoBundle) -> tuple[CaseContract, ...]:
    outcomes: list[CaseContract] = []
    for item in bundle.cases:
        inputs = prepared_inputs(item)
        case = CaseContract(**inputs.model_dump(), baseline=bundle.vendor)
        if not case.evidence.extraction.failure_code:
            case = review_case(
                case,
                operator_id="SIMULATED_DEMO_SOURCE_REVIEW",
                destination_instructions_checked=True,
            )
        outcomes.append(complete_case(case))
    return tuple(outcomes)


def seed_demo(bundle: DemoBundle, directory: Path) -> tuple[UUID, ...]:
    """Explicit private demo setup; refuse existing directories, leave actions human."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    store = SQLiteStore(directory / "payproof.sqlite3")
    try:
        store.put_vendor(bundle.vendor, operator_id="SYNTHETIC_DEMO_SETUP")
        return tuple(
            store.create_case(
                prepared_inputs(item), bundle.vendor.vendor_id, operator_id="SYNTHETIC_DEMO_SETUP"
            ).case_id
            for item in bundle.cases
        )
    finally:
        store.close()


def demo_passes(proof: ProofArtifact) -> bool:
    return all(
        outcome.comparison is not None
        and outcome.comparison.state == item.expected_state
        and set(item.required_reasons).issubset(outcome.comparison.reason_codes)
        for item, outcome in zip(proof.bundle.cases, proof.outcomes, strict=True)
    )


def render_proof(proof: ProofArtifact) -> str:
    """All metric numerators/denominators come from the retained run artifact."""
    gold = next(t for t in proof.gold.tracks if t.track == "gold_comparison")
    gate = next(t for t in proof.gold.tracks if t.track == "gold_review_gate")
    m = gold.metrics
    rows = (
        ("State classifications", f"{m.correct_state_classifications}/{m.total_cases}"),
        ("Exact state/reasons/values/evidence", f"{m.exact_correct_cases}/{m.total_cases}"),
        (
            "Consequential changes detected as correct VERIFY",
            f"{m.consequential_changes_detected}/{m.consequential_changes}",
        ),
        ("Changed cases not detected as correct VERIFY", str(m.consequential_changes_missed)),
        ("Changed cases abstained UNCERTAIN", str(m.changed_cases_abstained)),
        ("Critical false UNCHANGED", str(m.critical_false_unchanged)),
        ("False VERIFY on unchanged cases", str(m.unchanged_cases_incorrectly_escalated)),
        (
            "Correct UNCERTAIN, including required reasons",
            f"{m.uncertain_cases_handled_correctly}/{m.expected_uncertain_cases}",
        ),
        (
            "Uncertain-state recall (state only)",
            f"{m.uncertainty_recall.numerator}/{m.uncertainty_recall.denominator}",
        ),
        ("Unsafe definitive states on uncertain cases", str(m.unsafe_definitive_on_uncertain)),
        ("Deterministic comparison scoring failures", str(m.deterministic_comparison_failures)),
        ("Failed gold operations", str(m.failed_operations)),
        (
            "Extraction accuracy / grounding / schema failure rate",
            "NOT_RUN — gold observations supplied",
        ),
    )
    parts = [
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>PayProof evidence proof</title>',
        "<style>body{max-width:1000px;margin:2rem auto;padding:1rem;font:16px system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f4f4;padding:1rem}td,th{border:1px solid #888;padding:.5rem;text-align:left}table{border-collapse:collapse}aside{border:2px solid #975600;padding:1rem}</style>",
        "<h1>PayProof: evidence and mechanism proof</h1><aside>Payment authorization: not provided. Source review, deterministic comparison and independent human verification are separate actions. All demonstration contacts and accounts are fictional.</aside>",
        "<p>Curated synthetic observations, not live extraction accuracy. Report source review is explicitly simulated; no independent-verification record is created. Operator seed cases start unreviewed and uncompared.</p>",
        f"<p>Demonstration checks: {'PASS' if demo_passes(proof) else 'FAIL'}. These selected examples are not held-out benchmark performance.</p>",
    ]
    for item, case in zip(proof.bundle.cases, proof.outcomes, strict=True):
        parts.extend(
            (
                f"<h2>{escape(item.case_id)} — {escape(item.title)}</h2>",
                f'<p>Declared expectation: {item.expected_state} / {escape(", ".join(item.required_reasons))}. <a href="http://127.0.0.1:8000/operator/cases/{case.evidence.request_id}">Operator case (same seeded IDs on your local server)</a></p>',
                "<h3>Deterministic gate and separate human status</h3>",
                f"<pre>{escape(render_result(case))}</pre>",
                "<p>Independent human verification: NOT_VERIFIED. No autonomous confirmation; no account ownership assertion.</p>",
                "<details><summary>Original sources, old/new origins, exact spans and competing context</summary>",
                f"<pre>{escape(render_evidence(case))}</pre></details>",
            )
        )
    parts.extend(
        (
            "<h2>Gold deterministic comparison — supplied gold observations, simulated source review</h2>",
            f"<p>Saved track status: <strong>{gold.status}</strong>. Dataset: {escape(proof.gold.dataset_id)}; label review: {escape(proof.gold.independent_label_review)}. Run: {escape(proof.gold.run_at)}. Independent human verification and real source-review quality: NOT_EVALUATED.</p>",
            f"<p>Input artifact: {escape(proof.gold_path)}<br>Artifact SHA-256: {proof.gold_sha256}<br>Corpus SHA-256: {proof.gold.corpus_sha256}</p>",
            "<table><tr><th>Gold metric only</th><th>Saved result</th></tr>",
        )
    )
    parts.extend(
        f"<tr><td>{escape(label)}</td><td>{escape(value)}</td></tr>" for label, value in rows
    )
    parts.extend(
        (
            "</table><p>UNCERTAIN on a changed destination is an abstention, not successful change detection. Zero observed critical misses is limited to this corpus/track; it does not prove omission immunity.</p>",
            f"<p>Critical miss IDs: {escape(', '.join(m.critical_miss_case_ids) or 'none recorded')}.</p>",
            "<details><summary>Every failing gold case and scoring category</summary><ul>",
        )
    )
    for outcome in gold.outcomes:
        if not outcome.exact_correct:
            parts.append(
                f"<li>{escape(outcome.case_id)}: {escape('; '.join(i.stage + ':' + i.code + ' — ' + i.detail for i in outcome.issues))}</li>"
            )
    parts.extend(
        (
            "</ul></details><h2>Unreviewed gold source-review gate — separate diagnostic track</h2>",
            f"<p>Status: {gate.status}. State matches {gate.metrics.correct_state_classifications}/{gate.metrics.total_cases}; exact matches {gate.metrics.exact_correct_cases}/{gate.metrics.total_cases}. The expected result without review is abstention. These are not extraction or end-to-end successes.</p>",
            "<h2>Live extraction: BLOCKED / NOT_CONFIGURED</h2>",
            f"<p>Saved attempt: {escape(proof.live_status_path)}; SHA-256: {proof.live_status_sha256}; date: {escape(proof.live_status.date)}. Provider calls: {proof.live_status.provider_calls}; completed cases: {proof.live_status.completed_live_cases}; planned: {proof.live_status.planned_cases}.</p>",
            "<p>Field extraction accuracy, evidence grounding validity and schema failure rate: NOT_MEASURED. No live fixture substitution.</p>",
            "<h2>Live end-to-end: NOT_MEASURED</h2><p>No completed live predictions. End-to-end state accuracy, change recall, critical misses and uncertainty handling cannot be reported for live extraction. Gold, local examples and live metrics are never pooled.</p>",
            "<h2>Limitations</h2><p>Synthetic data; independent label review pending. Conservative multiple-destination abstention reduces supported-change recall. Supported comparison is full checksum-valid GB/DE IBAN only; no OCR, payments or banking integrations. Lexical discovery cannot prove payment intent or exhaustive coverage. Human callback actions are self-reported and scoped to a current revision. The fictional callback must not be called.</p>",
            '<p>Full retained inputs, outputs and benchmark records: <a href="proof.json">proof.json</a>. This report is static evidence, not an operator action.</p></html>',
        )
    )
    return "\n".join(parts)


def read_artifact(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(16_777_217)
    if len(raw) > 16_777_216:
        raise ValueError("artifact size limit exceeded")
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="New proof directory; never overwritten"
    )
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--live-status", type=Path, default=DEFAULT_LIVE)
    parser.add_argument(
        "--seed-data-dir", type=Path, help="Optional NEW private operator data directory"
    )
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.seed_data_dir and args.seed_data_dir.exists():
            raise FileExistsError("retain existing demonstration output")
        settings = load_settings(os.environ)
        gold_raw, live_raw = read_artifact(args.gold), read_artifact(args.live_status)
        bundle = load_demo()
        proof = ProofArtifact(
            bundle=bundle,
            outcomes=run_demo(bundle),
            gold_path=str(args.gold),
            gold_sha256=hashlib.sha256(gold_raw).hexdigest(),
            gold=parse_contract(RunReport, gold_raw),
            live_status_path=str(args.live_status),
            live_status_sha256=hashlib.sha256(live_raw).hexdigest(),
            live_status=parse_contract(BlockedLiveAttempt, live_raw),
        )
        reject_configured_secrets(proof.model_dump(mode="json"), settings)
        args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        # Render only from the saved canonical artifact, not in-memory predictions.
        saved_path = args.output / "proof.json"
        saved_path.write_text(proof.model_dump_json(indent=2) + "\n", encoding="utf-8")
        saved = parse_contract(ProofArtifact, saved_path.read_bytes())
        (args.output / "report.html").write_text(render_proof(saved), encoding="utf-8")
        if args.seed_data_dir:
            seed_demo(bundle, args.seed_data_dir)
        print("Synthetic mechanism proof: " + ("PASS" if demo_passes(saved) else "FAIL"))
        print(f"Saved evidence report: {args.output / 'report.html'}")
        print("Gold benchmark status: " + ("PASS" if saved.gold.passed else "FAIL"))
        print("Live extraction: BLOCKED / NOT_CONFIGURED; live end-to-end: NOT_MEASURED")
        return 0 if demo_passes(saved) else 1
    except (OSError, ValueError) as error:
        print(f"Proof generation failed: {type(error).__name__}; no passing result claimed.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
