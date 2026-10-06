"""Frozen-corpus gold, review-gate, extraction, and replay evaluation CLI."""

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from payproof.benchmark_scoring import (
    DESTINATION_FIELDS,
    FieldScore,
    Issue,
    Metrics,
    Outcome,
    score_content,
    score_extraction,
    summarize,
)
from payproof.cases import candidate_identity
from payproof.comparison import compare
from payproof.config import ConfigurationError, Settings, load_settings
from payproof.evaluation_contracts import BenchmarkCase, BenchmarkCorpus, BenchmarkDataset
from payproof.extraction import ExtractionAttempt, extract_attempt
from payproof.extraction_contract import (
    EXTRACTION_INSTRUCTIONS,
    PROMPT_VERSION,
    WireExtractionPayload,
    structured_output_schema,
)
from payproof.schemas import (
    CaseContract,
    Contract,
    PaymentRequestEvidence,
    SourceReview,
    TrustedVendorRecord,
)
from payproof.validation import parse_contract

DEFAULT_CORPUS = Path("benchmarks/phase1-v1/cases.json")
TrackName = Literal[
    "gold_comparison", "gold_review_gate", "conditional_pipeline", "extraction_review_gate"
]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class AttemptRecord(Contract):
    case_id: str
    evidence: PaymentRequestEvidence | None
    exception_type: str | None = None
    provider_response_sha256: str | None = None
    elapsed_seconds: float
    wire_schema_status: Literal["PASS", "FAIL", "UNAVAILABLE"] = "UNAVAILABLE"


class TrackReport(Contract):
    track: TrackName
    status: Literal["PASS", "FAIL"]
    review_protocol: str
    metrics: Metrics
    outcomes: tuple[Outcome, ...]


class AttemptTiming(Contract):
    attempts: int
    median_seconds: float
    max_seconds: float


class RunReport(Contract):
    report_version: Literal["payproof-benchmark-run-v1"] = "payproof-benchmark-run-v1"
    run_at: str
    dataset_id: str
    corpus_sha256: str
    independent_label_review: str
    split: str
    rule_version: str
    git_commit: str | None
    dirty_worktree: bool
    tracked_diff_sha256: str
    code_sha256: dict[str, str]
    python_version: str
    prompt_version: str
    prompt_sha256: str
    schema_sha256: str
    extraction_mode: str
    configured_model: str | None
    extraction_status: Literal["NOT_RUN", "PASS", "FAIL"]
    extraction_source: Literal["NOT_RUN", "CURRENT_CONFIGURATION", "REPLAY"]
    replay_input_sha256: str | None
    workflow_action_enforcement: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    independent_verification: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    provider_cost: None = None
    attempt_timing: AttemptTiming | None
    tracks: tuple[TrackReport, ...]
    extraction_attempts: tuple[AttemptRecord, ...]
    scoring_sha256: str
    passed: bool


def simulated_case(
    case: BenchmarkCase,
    baseline: TrustedVendorRecord | None,
    evidence: PaymentRequestEvidence,
    *,
    reviewed: bool,
    track: TrackName,
) -> CaseContract:
    """Test-only acknowledgement of observations; never a human attestation."""
    review = None
    if reviewed and evidence.extraction.failure_code is None:
        review = SourceReview(
            review_id=uuid5(NAMESPACE_URL, f"payproof:{track}:review:{case.case_id}"),
            request_id=evidence.request_id,
            attempt_id=evidence.extraction.attempt_id,
            operator_id=(
                "SIMULATED_GOLD_SOURCE_REVIEW"
                if track == "gold_comparison"
                else "SIMULATED_MODEL_OUTPUT_REVIEW"
            ),
            reviewed_at=evidence.extraction.extracted_at + timedelta(seconds=1),
            destination_instructions_checked=True,
            reviewed_evidence_ids=tuple(s.evidence_id for s in evidence.spans()),
            # Derive from observations only, never the gold normalized label.
            payment_identity=candidate_identity(evidence),
        )
    return CaseContract(sources=case.sources, evidence=evidence, baseline=baseline, review=review)


def evaluate_case(
    case: BenchmarkCase,
    baseline: TrustedVendorRecord | None,
    evidence: PaymentRequestEvidence | None,
    *,
    track: TrackName,
    attempt_exception: str | None = None,
) -> Outcome:
    reviewed = track in ("gold_comparison", "conditional_pipeline")
    extracted = track in ("conditional_pipeline", "extraction_review_gate")
    result = None
    review = None
    issues: list[Issue] = []
    fields: tuple[FieldScore, ...] = ()
    extraction_correct: bool | None = None
    failed = evidence is None
    if evidence is None:
        issues.append(
            Issue(
                stage="extraction",
                code="EXTRACTION_EXCEPTION",
                detail=attempt_exception or "Unavailable extraction record.",
            )
        )
        extraction_correct = False
    else:
        # Validate replay/provider records before feeding comparison or scoring.
        try:
            if evidence.request_id != case.gold_evidence.request_id:
                raise ValueError("Request binding mismatch")
            CaseContract(sources=case.sources, evidence=evidence, baseline=baseline)
        except (ValueError, ValidationError) as error:
            failed = True
            issues.append(
                Issue(
                    stage="extraction" if extracted else "comparison",
                    code="EVIDENCE_MISGROUNDING",
                    detail=type(error).__name__,
                )
            )
        else:
            if extracted:
                if evidence.extraction.failure_code:
                    failed = True
                    issues.append(
                        Issue(
                            stage="extraction",
                            code=evidence.extraction.failure_code,
                            detail="Extraction failed; uncertain output is not a successful classification.",
                        )
                    )
                    extraction_correct = False
                else:
                    fields, extraction_issues = score_extraction(case, evidence)
                    issues.extend(extraction_issues)
                    extraction_correct = not extraction_issues
            try:
                snapshot = simulated_case(case, baseline, evidence, reviewed=reviewed, track=track)
                review = snapshot.review
                result = compare(
                    snapshot,
                    comparison_id=uuid5(
                        NAMESPACE_URL, f"payproof:{track}:comparison:{case.case_id}"
                    ),
                    compared_at=evidence.extraction.extracted_at + timedelta(seconds=2),
                    selected_vendor_id=case.selected_vendor_id,
                )
                # Also reject unchecked/malformed results from a faulty engine.
                CaseContract(
                    sources=snapshot.sources,
                    evidence=evidence,
                    baseline=baseline,
                    review=review,
                    comparison=result,
                )
            except Exception as error:
                # Do not abort the corpus or echo provider/source/secret exception text.
                failed = True
                result = None
                issues.append(
                    Issue(
                        stage="comparison", code="COMPARISON_EXCEPTION", detail=type(error).__name__
                    )
                )
            if result is not None and not failed:
                issues.extend(score_content(case, baseline, evidence, result, reviewed=reviewed))
    # Expected labels enter only after the predictor has returned/failed.
    expected = case.after_gold_source_review if reviewed else case.without_source_review
    state_correct = not failed and result is not None and result.state == expected.state
    reasons_correct = (
        not failed and result is not None and result.reason_codes == expected.reason_codes
    )
    if result is not None and not failed:
        if not state_correct:
            issues.append(
                Issue(
                    stage="comparison",
                    code="STATE_MISMATCH",
                    detail=f"Expected {expected.state}; observed {result.state}.",
                )
            )
        if not reasons_correct:
            issues.append(
                Issue(
                    stage="comparison",
                    code="REASON_MISMATCH",
                    detail=f"Expected {expected.reason_codes}; observed {result.reason_codes}.",
                )
            )
    content_correct = (
        not failed
        and result is not None
        and not any(i.code == "RESULT_EVIDENCE_INCONSISTENCY" for i in issues)
    )
    # An incorrect extracted destination causing a wrong result is not an engine
    # failure on gold inputs. Preserve the end-to-end consequence and root cause.
    extraction_error_fields = {i.field for i in issues if i.stage == "extraction"}
    destination_extraction_error = bool(extraction_error_fields.intersection(DESTINATION_FIELDS))
    if extracted:
        issues = [
            Issue(stage="extraction", code=f"PIPELINE_{i.code}", field=i.field, detail=i.detail)
            if i.stage == "comparison"
            and (
                i.code == "RESULT_EVIDENCE_INCONSISTENCY"
                and i.field in extraction_error_fields
                or i.code in ("STATE_MISMATCH", "REASON_MISMATCH")
                and destination_extraction_error
            )
            else i
            for i in issues
        ]
    destination_correct = (
        not failed
        and state_correct
        and reasons_correct
        and not any(i.field is None or i.field in DESTINATION_FIELDS for i in issues)
    )
    return Outcome(
        case_id=case.case_id,
        expected=expected,
        result=result,
        review=review,
        failed_operation=failed,
        state_correct=state_correct,
        reasons_correct=reasons_correct,
        content_correct=content_correct,
        destination_correct=destination_correct,
        extraction_correct=extraction_correct,
        field_scores=fields,
        issues=tuple(issues),
    )


def evaluate_track(
    corpus: BenchmarkDataset, track: TrackName, attempts: tuple[AttemptRecord, ...] = ()
) -> TrackReport:
    by_baseline = {b.key: b.record for b in corpus.baselines}
    by_case = {a.case_id: a for a in attempts}
    extracted = track in ("conditional_pipeline", "extraction_review_gate")
    outcomes = []
    for case in corpus.cases:
        attempt = by_case.get(case.case_id)
        outcomes.append(
            evaluate_case(
                case,
                by_baseline.get(case.baseline_key) if case.baseline_key else None,
                attempt.evidence if attempt else None if extracted else case.gold_evidence,
                track=track,
                attempt_exception=attempt.exception_type if attempt else None,
            )
        )
    metrics = summarize(corpus.cases, tuple(outcomes))
    return TrackReport(
        track=track,
        status="PASS" if all(o.exact_correct for o in outcomes) else "FAIL",
        review_protocol="NO_SOURCE_REVIEW"
        if "gate" in track
        else "SIMULATED_GOLD_SOURCE_REVIEW"
        if track == "gold_comparison"
        else "SIMULATED_MODEL_OUTPUT_REVIEW",
        metrics=metrics,
        outcomes=tuple(outcomes),
    )


def wire_schema_status(attempt: ExtractionAttempt) -> Literal["PASS", "FAIL", "UNAVAILABLE"]:
    """Assess only observed output; provider/protocol failure is not a schema result.

    Raw provider bodies never enter reports. Some safely discarded bodies cannot
    be assessed, so missing diagnostic information remains UNAVAILABLE.
    """
    if attempt.evidence.extraction.method != "AI":
        return "UNAVAILABLE"
    failure = attempt.evidence.extraction.failure_code
    if failure is None or failure == "EVIDENCE_INVALID":
        return "PASS"
    if failure != "INVALID_RESPONSE" or attempt.raw_provider_response is None:
        return "UNAVAILABLE"
    try:
        body = json.loads(attempt.raw_provider_response)
        texts = [
            part["text"]
            for item in body.get("output", [])
            if item.get("type") == "message" and item.get("role") == "assistant"
            for part in item.get("content", [])
            if part.get("type") == "output_text" and isinstance(part.get("text"), str)
        ]
        if len(texts) != 1:
            return "UNAVAILABLE"
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
        return "UNAVAILABLE"
    try:
        parse_contract(WireExtractionPayload, texts[0])
    except (ValueError, ValidationError):
        return "FAIL"
    return "PASS"


def collect_attempts(corpus: BenchmarkDataset, settings: Settings) -> tuple[AttemptRecord, ...]:
    records = []
    for case in corpus.cases:
        started = perf_counter()
        try:
            # Sources only: no baseline or gold labels enter the extractor.
            attempt = extract_attempt(
                case.sources, settings=settings, request_id=case.gold_evidence.request_id
            )
            records.append(
                AttemptRecord(
                    case_id=case.case_id,
                    evidence=attempt.evidence,
                    provider_response_sha256=digest(attempt.raw_provider_response)
                    if attempt.raw_provider_response is not None
                    else None,
                    elapsed_seconds=perf_counter() - started,
                    wire_schema_status=wire_schema_status(attempt),
                )
            )
        except Exception as error:
            records.append(
                AttemptRecord(
                    case_id=case.case_id,
                    evidence=None,
                    exception_type=type(error).__name__,
                    elapsed_seconds=perf_counter() - started,
                )
            )
    return tuple(records)


def _git(*args: str) -> bytes:
    try:
        return subprocess.run(["git", *args], check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return b""


def code_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    paths = [*sorted((root / "payproof").glob("*.py")), root / "Makefile", root / "pyproject.toml"]
    return {str(p.relative_to(root)): digest(p.read_bytes()) for p in paths if p.is_file()}


def run_benchmark(
    corpus_path: Path,
    *,
    settings: Settings | None = None,
    replay_path: Path | None = None,
    corpus_model: type[BenchmarkDataset] = BenchmarkCorpus,
) -> RunReport:
    raw = corpus_path.read_bytes()
    corpus = parse_contract(corpus_model, raw)
    corpus_hash = digest(raw)
    # Freeze provenance before predictions.
    provenance = code_hashes()
    commit = _git("rev-parse", "HEAD").decode().strip() or None
    dirty = bool(_git("status", "--porcelain"))
    diff_hash = digest(_git("diff", "HEAD", "--binary"))
    attempts: tuple[AttemptRecord, ...] = ()
    extraction_source: Literal["NOT_RUN", "CURRENT_CONFIGURATION", "REPLAY"] = "NOT_RUN"
    replay_hash = None
    mode, model = "NOT_RUN", None
    if replay_path is not None:
        replay_raw = replay_path.read_bytes()
        previous = parse_contract(RunReport, replay_raw)
        if previous.corpus_sha256 != corpus_hash or previous.rule_version != corpus.rule_version:
            raise ValueError("Replay corpus/rule hash mismatch")
        attempts = previous.extraction_attempts
        if len(attempts) != len(corpus.cases) or {a.case_id for a in attempts} != {
            c.case_id for c in corpus.cases
        }:
            raise ValueError("Replay must contain exactly one attempt for every corpus case")
        extraction_source = "REPLAY"
        replay_hash = digest(replay_raw)
        mode, model = previous.extraction_mode, previous.configured_model
    elif settings is not None:
        extraction_source = "CURRENT_CONFIGURATION"
        mode, model = settings.extraction_mode, settings.provider_model
        attempts = collect_attempts(corpus, settings)
    tracks = [evaluate_track(corpus, "gold_comparison"), evaluate_track(corpus, "gold_review_gate")]
    if extraction_source != "NOT_RUN":
        tracks.extend(
            (
                evaluate_track(corpus, "conditional_pipeline", attempts),
                evaluate_track(corpus, "extraction_review_gate", attempts),
            )
        )
    scoring = [
        {
            "track": t.track,
            "metrics": t.metrics.model_dump(mode="json"),
            "cases": [
                {
                    "case_id": o.case_id,
                    "state": o.result.state if o.result else None,
                    "reasons": o.result.reason_codes if o.result else (),
                    "exact_correct": o.exact_correct,
                    "issues": [i.model_dump(mode="json") for i in o.issues],
                }
                for o in t.outcomes
            ],
        }
        for t in tracks
    ]
    extraction_status: Literal["NOT_RUN", "PASS", "FAIL"] = "NOT_RUN"
    if attempts:
        extraction_status = tracks[2].status
    return RunReport(
        run_at=datetime.now(UTC).isoformat(),
        dataset_id=corpus.dataset_id,
        corpus_sha256=corpus_hash,
        independent_label_review=corpus.independent_label_review,
        split=corpus.split,
        rule_version=corpus.rule_version,
        git_commit=commit,
        dirty_worktree=dirty,
        tracked_diff_sha256=diff_hash,
        code_sha256=provenance,
        python_version=platform.python_version(),
        prompt_version=PROMPT_VERSION,
        prompt_sha256=digest(EXTRACTION_INSTRUCTIONS.encode()),
        schema_sha256=digest(json.dumps(structured_output_schema(), sort_keys=True).encode()),
        extraction_mode=mode,
        configured_model=model,
        extraction_status=extraction_status,
        extraction_source=extraction_source,
        replay_input_sha256=replay_hash,
        attempt_timing=AttemptTiming(
            attempts=len(attempts),
            median_seconds=statistics.median(a.elapsed_seconds for a in attempts),
            max_seconds=max(a.elapsed_seconds for a in attempts),
        )
        if attempts
        else None,
        tracks=tuple(tracks),
        extraction_attempts=attempts,
        scoring_sha256=digest(json.dumps(scoring, sort_keys=True).encode()),
        passed=all(t.status == "PASS" for t in tracks),
    )


def render_summary(report: RunReport) -> str:
    lines = [
        "PayProof benchmark",
        f"Dataset: {report.dataset_id}",
        f"Corpus SHA-256: {report.corpus_sha256}",
        f"Label review: {report.independent_label_review}; {report.split}",
        "Human-action enforcement and independent verification: NOT_EVALUATED",
        "",
    ]
    for track in report.tracks:
        m = track.metrics
        lines.extend(
            (
                f"Track: {track.track} ({track.status}; {track.review_protocol})",
                f"Total cases: {m.total_cases}",
                f"Correct states: {m.correct_state_classifications}/{m.total_cases}",
                f"Exact correct (state/reasons/values/evidence): {m.exact_correct_cases}/{m.total_cases}",
            )
        )
        if "gate" not in track.track:
            lines.extend(
                (
                    f"Consequential changes: {m.consequential_changes}",
                    f"Detected: {m.consequential_changes_detected}",
                    f"Missed (not detected as correct VERIFY): {m.consequential_changes_missed}",
                    f"Supported changes detected: {m.supported_changes_detected}/{m.supported_consequential_changes}",
                    f"Changed cases abstained: {m.changed_cases_abstained}",
                    f"Changed cases failed: {m.changed_cases_failed}",
                    f"Critical missed changes (false UNCHANGED): {m.critical_false_unchanged}",
                    f"False escalations (incorrect VERIFY): {m.unchanged_cases_incorrectly_escalated}",
                    f"Uncertain handled correctly: {m.uncertain_cases_handled_correctly}/{m.expected_uncertain_cases}",
                )
            )
        lines.extend(
            (
                f"Extraction failures: {m.extraction_failures if m.extraction_failures is not None else 'NOT_RUN (gold inputs)'}",
                f"Extraction error cases: {m.extraction_error_cases if m.extraction_error_cases is not None else 'NOT_RUN'}",
                f"Deterministic-comparison failures: {m.deterministic_comparison_failures}",
                f"Failed operations: {m.failed_operations}",
            )
        )
        for outcome in track.outcomes:
            if not outcome.exact_correct:
                detail = "; ".join(
                    f"{i.stage}:{i.code}{'[' + i.field + ']' if i.field else ''}: {i.detail}"
                    for i in outcome.issues
                )
                lines.append(f"FAIL {outcome.case_id}: {detail}")
        lines.append("")
    lines.extend(
        (
            f"Extraction: {report.extraction_status}; mode={report.extraction_mode}; source={report.extraction_source}",
            "Gold results are not live extraction accuracy. UNCERTAIN is not successful change detection.",
            f"Scoring SHA-256: {report.scoring_sha256}",
        )
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the frozen PayProof diagnostic corpus")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument(
        "--output", type=Path, help="Write report.json and summary.txt to this directory"
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--with-extraction",
        action="store_true",
        help="Attempt all sources using current explicit extraction configuration",
    )
    modes.add_argument(
        "--replay", type=Path, help="Replay stored extraction observations without provider calls"
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the structured report instead of its summary"
    )
    args = parser.parse_args(argv)
    try:
        report = run_benchmark(
            args.corpus,
            settings=load_settings(os.environ) if args.with_extraction else None,
            replay_path=args.replay,
        )
        summary = render_summary(report)
        if args.output:
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / "report.json").write_text(
                report.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            (args.output / "summary.txt").write_text(summary, encoding="utf-8")
        print(
            report.model_dump_json(indent=2) if args.json else summary,
            end="\n" if args.json else "",
        )
        return 0 if report.passed else 1
    except (ConfigurationError, ValidationError, ValueError, OSError) as error:
        print(
            f"Benchmark input/configuration failed: {type(error).__name__}; no successful report produced.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
