"""Scoring, stage attribution, safe failures, replay, and frozen-corpus regression."""

import json

import pytest

from payproof.benchmark_harness import (
    DEFAULT_CORPUS,
    evaluate_case,
    main,
    run_benchmark,
)
from payproof.benchmark_scoring import score_extraction, summarize
from payproof.comparison import compare as real_compare
from payproof.config import Settings
from payproof.evaluation_contracts import BenchmarkCorpus, BenchmarkExpectation
from payproof.extraction import ExtractionAttempt
from payproof.schemas import CaseContract, PaymentRequestEvidence


@pytest.fixture
def corpus():
    return BenchmarkCorpus.model_validate_json(DEFAULT_CORPUS.read_bytes())


def test_frozen_thirty_case_gold_and_review_gate_regression(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Gold comparison must not call extraction")

    monkeypatch.setattr("payproof.benchmark_harness.extract_attempt", forbidden)
    report = run_benchmark(DEFAULT_CORPUS)
    # Frozen gold labels are retained: source guard deliberately abstains on
    # historical/lookup IBAN competition instead of trusting role extraction.
    assert not report.passed and report.extraction_status == "NOT_RUN"
    gold, gate = report.tracks
    assert gold.metrics.total_cases == 30
    assert gold.metrics.correct_state_classifications == gold.metrics.exact_correct_cases == 28
    assert gold.metrics.consequential_changes == 13
    assert gold.metrics.consequential_changes_detected == 8
    assert gold.metrics.consequential_changes_missed == 5
    assert gold.metrics.changed_cases_abstained == 5
    assert gold.metrics.critical_false_unchanged == 0
    assert gold.metrics.unchanged_cases_incorrectly_escalated == 0
    assert gold.metrics.uncertain_cases_handled_correctly == 13
    assert gold.metrics.extraction_failures is None
    assert gold.metrics.deterministic_comparison_failures == 2
    assert gate.metrics.exact_correct_cases == 28
    assert [o.case_id for o in gold.outcomes if not o.exact_correct] == ["PP-09", "PP-12"]
    assert all(o.result.state == "UNCERTAIN" and o.review is None for o in gate.outcomes)
    assert report.workflow_action_enforcement == "NOT_EVALUATED"
    assert report.independent_label_review == "PENDING"


def test_gold_predictions_and_scoring_are_reproducible():
    first = run_benchmark(DEFAULT_CORPUS)
    second = run_benchmark(DEFAULT_CORPUS)
    assert first.scoring_sha256 == second.scoring_sha256
    assert first.tracks == second.tracks
    assert first.code_sha256 == second.code_sha256


def test_expected_labels_do_not_enter_the_comparator(corpus):
    case = corpus.cases[0].model_copy(
        update={
            "after_gold_source_review": BenchmarkExpectation(
                state="UNCHANGED", reason_codes=("DESTINATION_MATCH",)
            ),
        }
    )
    # Deliberately bypass corpus label validation to test predictor/scorer separation.
    outcome = evaluate_case(
        case, corpus.baselines[0].record, case.gold_evidence, track="gold_comparison"
    )
    assert outcome.result.state == "VERIFY"
    assert not outcome.state_correct
    assert any(i.code == "STATE_MISMATCH" for i in outcome.issues)
    assert outcome.case_id == "PP-01"


def test_comparison_exception_is_localized_and_does_not_abort_corpus(monkeypatch, corpus):
    request_id = corpus.cases[4].gold_evidence.request_id

    def faulty(snapshot, **kwargs):
        if snapshot.evidence.request_id == request_id:
            raise RuntimeError("private diagnostic text must not be emitted")
        return real_compare(snapshot, **kwargs)

    monkeypatch.setattr("payproof.benchmark_harness.compare", faulty)
    report = run_benchmark(DEFAULT_CORPUS)
    gold = report.tracks[0]
    assert not report.passed
    assert gold.metrics.total_cases == 30
    assert gold.metrics.correct_state_classifications == 27
    assert gold.metrics.deterministic_comparison_failures == 3
    assert gold.metrics.extraction_failures is None
    failed = [o for o in gold.outcomes if not o.exact_correct]
    assert [o.case_id for o in failed] == ["PP-05", "PP-09", "PP-12"]
    assert failed[0].issues[0].detail == "RuntimeError"
    assert "private diagnostic" not in report.model_dump_json()


def test_correct_state_with_missing_blocker_evidence_is_not_an_exact_pass(monkeypatch, corpus):
    request_id = corpus.cases[20].gold_evidence.request_id

    def faulty(snapshot, **kwargs):
        result = real_compare(snapshot, **kwargs)
        return (
            result.model_copy(update={"missing_information": ()})
            if snapshot.evidence.request_id == request_id
            else result
        )

    monkeypatch.setattr("payproof.benchmark_harness.compare", faulty)
    report = run_benchmark(DEFAULT_CORPUS)
    gold = report.tracks[0]
    assert gold.metrics.correct_state_classifications == 28
    assert gold.metrics.exact_correct_cases == 27
    assert gold.metrics.uncertain_cases_handled_correctly == 12
    assert gold.metrics.deterministic_comparison_failures == 3
    assert [o.case_id for o in gold.outcomes if not o.exact_correct] == ["PP-09", "PP-12", "PP-21"]


def test_disabled_extraction_is_thirty_failures_not_thirteen_successful_abstentions():
    report = run_benchmark(DEFAULT_CORPUS, settings=Settings(extraction_mode="disabled"))
    assert report.extraction_status == "FAIL"
    assert not report.passed
    assert len(report.extraction_attempts) == 30
    pipeline = report.tracks[2]
    assert pipeline.metrics.extraction_failures == 30
    assert pipeline.metrics.correct_state_classifications == 0
    assert pipeline.metrics.uncertain_cases_handled_correctly == 0
    assert pipeline.metrics.deterministic_comparison_failures == 0
    assert pipeline.metrics.confusion["UNCERTAIN"]["FAILED"] == 13
    assert all(o.result.state == "UNCERTAIN" for o in pipeline.outcomes)
    assert all(o.issues[0].code == "NOT_CONFIGURED" for o in pipeline.outcomes)


def test_extraction_exception_is_localized_separately_from_gold_comparison(monkeypatch, corpus):
    by_sources = {tuple(s.source_id for s in c.sources): c for c in corpus.cases}

    def fake_attempt(sources, *, settings, request_id):
        case = by_sources[tuple(s.source_id for s in sources)]
        if case.case_id == "PP-03":
            raise TimeoutError("do not print secret values")
        # Injected gold responses are a unit-test stub, never a measured AI run.
        return ExtractionAttempt(
            evidence=case.gold_evidence,
            source_digests=tuple((s.source_id, s.sha256) for s in sources),
        )

    monkeypatch.setattr("payproof.benchmark_harness.extract_attempt", fake_attempt)
    report = run_benchmark(DEFAULT_CORPUS, settings=Settings())
    assert report.tracks[0].status == "FAIL"
    pipeline = report.tracks[2]
    assert pipeline.metrics.extraction_failures == 1
    assert pipeline.metrics.deterministic_comparison_failures == 2
    assert [o.case_id for o in pipeline.outcomes if not o.exact_correct] == [
        "PP-03",
        "PP-09",
        "PP-12",
    ]
    assert "do not print" not in report.model_dump_json()


def test_wrong_role_omission_abstains_and_is_attributed_to_extraction(corpus):
    case = corpus.cases[8]
    retired = case.non_destination_spans[0]
    data = json.loads(case.gold_evidence.model_dump_json())
    candidate = data["account_identifier"]["candidates"][0]
    candidate["value"] = retired.raw_value
    candidate["evidence"].update(
        {
            "source_id": str(retired.source_id),
            "extracted_value": retired.raw_value,
            "exact_excerpt": retired.exact_excerpt,
            "location": retired.location.model_dump(),
        }
    )
    evidence = PaymentRequestEvidence.model_validate_json(json.dumps(data))
    # This quote is real. Grounding alone cannot establish a current-payment role.
    CaseContract(sources=case.sources, evidence=evidence, baseline=corpus.baselines[0].record)
    outcome = evaluate_case(
        case, corpus.baselines[0].record, evidence, track="conditional_pipeline"
    )
    assert outcome.result.state == "UNCERTAIN"
    assert "DESTINATION_AMBIGUOUS" in outcome.result.reason_codes
    assert not outcome.destination_correct
    metrics = summarize((case,), (outcome,))
    assert metrics.critical_false_unchanged == 0
    assert metrics.critical_miss_case_ids == ()
    assert metrics.deterministic_comparison_failures == 0
    assert metrics.extraction_error_cases == 1
    assert any(i.code == "WRONG_ROLE" for i in outcome.issues)


def test_context_omission_does_not_count_as_a_missed_destination_change(corpus):
    case = corpus.cases[0]
    data = json.loads(case.gold_evidence.model_dump_json())
    data["amount"] = {"status": "MISSING", "candidates": []}
    evidence = PaymentRequestEvidence.model_validate_json(json.dumps(data))
    outcome = evaluate_case(
        case, corpus.baselines[0].record, evidence, track="conditional_pipeline"
    )
    assert outcome.result.state == "VERIFY" and outcome.destination_correct
    assert not outcome.exact_correct
    metrics = summarize((case,), (outcome,))
    assert metrics.consequential_changes_detected == 1
    assert metrics.extraction_error_cases == 1
    assert metrics.deterministic_comparison_failures == 0


def test_distinct_conflicting_candidates_cannot_be_deduplicated(corpus):
    case = corpus.cases[25]
    data = json.loads(case.gold_evidence.model_dump_json())
    data["account_identifier"]["status"] = "FOUND"
    data["account_identifier"]["candidates"] = data["account_identifier"]["candidates"][:1]
    data["account_identifier"]["candidates"][0]["evidence"]["extraction_status"] = "FOUND"
    evidence = PaymentRequestEvidence.model_validate_json(json.dumps(data))
    _, issues = score_extraction(case, evidence)
    assert any(i.field == "account_identifier" and i.code == "AMBIGUITY_LOSS" for i in issues)


def test_identical_mentions_and_equivalent_exact_excerpt_boundaries_are_accepted(corpus):
    case = corpus.cases[25]
    data = json.loads(case.gold_evidence.model_dump_json())
    # Same scheme literal is safely represented once; conflicting accounts remain.
    scheme = data["destination_scheme"]
    scheme["status"] = "FOUND"
    scheme["candidates"] = scheme["candidates"][:1]
    scheme["candidates"][0]["evidence"]["extraction_status"] = "FOUND"
    for candidate in data["account_identifier"]["candidates"]:
        span = candidate["evidence"]
        source = next(s for s in case.sources if str(s.source_id) == span["source_id"])
        span["location"]["char_end"] += 1
        span["exact_excerpt"] = source.text[
            span["location"]["char_start"] : span["location"]["char_end"]
        ]
    evidence = PaymentRequestEvidence.model_validate_json(json.dumps(data))
    CaseContract(sources=case.sources, evidence=evidence, baseline=corpus.baselines[0].record)
    _, issues = score_extraction(case, evidence)
    assert issues == ()


def test_replay_reproduces_scores_without_provider_calls(tmp_path, monkeypatch):
    original = run_benchmark(DEFAULT_CORPUS, settings=Settings())
    path = tmp_path / "original.json"
    path.write_text(original.model_dump_json())

    def forbidden(*args, **kwargs):
        raise AssertionError("Replay must not call extraction")

    monkeypatch.setattr("payproof.benchmark_harness.extract_attempt", forbidden)
    replay = run_benchmark(DEFAULT_CORPUS, replay_path=path)
    assert replay.extraction_source == "REPLAY"
    assert replay.scoring_sha256 == original.scoring_sha256
    assert replay.tracks == original.tracks


def test_replay_of_successful_validated_observations_keeps_original_evidence(
    tmp_path, monkeypatch, corpus
):
    by_sources = {tuple(s.source_id for s in c.sources): c for c in corpus.cases}

    def stub(sources, *, settings, request_id):
        case = by_sources[tuple(s.source_id for s in sources)]
        return ExtractionAttempt(
            evidence=case.gold_evidence,
            source_digests=tuple((s.source_id, s.sha256) for s in sources),
        )

    monkeypatch.setattr("payproof.benchmark_harness.extract_attempt", stub)
    original = run_benchmark(DEFAULT_CORPUS, settings=Settings())
    assert not original.passed
    path = tmp_path / "test-stub-only.json"
    path.write_text(original.model_dump_json())

    def forbidden(*args, **kwargs):
        raise AssertionError("Replay must consume original records")

    monkeypatch.setattr("payproof.benchmark_harness.extract_attempt", forbidden)
    replay = run_benchmark(DEFAULT_CORPUS, replay_path=path)
    assert not replay.passed
    assert replay.tracks == original.tracks
    assert replay.scoring_sha256 == original.scoring_sha256
    assert replay.extraction_attempts == original.extraction_attempts


@pytest.mark.parametrize("mutation", ["corpus_hash", "duplicate_attempt", "missing_attempt"])
def test_replay_rejects_wrong_corpus_and_missing_or_duplicate_attempts(tmp_path, mutation):
    original = run_benchmark(DEFAULT_CORPUS, settings=Settings())
    data = json.loads(original.model_dump_json())
    if mutation == "corpus_hash":
        data["corpus_sha256"] = "wrong"
    elif mutation == "duplicate_attempt":
        data["extraction_attempts"][0] = data["extraction_attempts"][1]
    else:
        data["extraction_attempts"].pop()
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        run_benchmark(DEFAULT_CORPUS, replay_path=path)


def test_cli_writes_real_report_and_summary_and_failure_exit_codes(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("PAYPROOF_EXTRACTION_MODE", raising=False)
    assert main(["--output", str(tmp_path / "gold")]) == 1
    output = capsys.readouterr().out
    assert "Correct states: 28/30" in output
    assert "Missed (not detected as correct VERIFY): 5" in output
    assert (tmp_path / "gold" / "summary.txt").read_text() == output
    assert main(["--with-extraction", "--output", str(tmp_path / "disabled"), "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["extraction_status"] == "FAIL"
    assert data["tracks"][2]["metrics"]["extraction_failures"] == 30
    assert main(["--corpus", str(tmp_path / "absent.json")]) == 2
    assert "no successful report" in capsys.readouterr().err


def test_project_cli_dispatches_the_new_benchmark(tmp_path, capsys):
    from payproof.cli import main as project_main

    assert project_main(["benchmark", "--output", str(tmp_path)]) == 1
    assert "Total cases: 30" in capsys.readouterr().out
    assert (tmp_path / "report.json").exists()
