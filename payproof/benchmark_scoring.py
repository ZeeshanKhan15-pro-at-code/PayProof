"""Independent label/evidence scoring; predictions never receive expected labels."""

from collections import Counter
from typing import Literal

from payproof.evaluation_contracts import BenchmarkCase, BenchmarkExpectation
from payproof.schemas import (
    EVIDENCE_FIELDS,
    ComparisonResult,
    Contract,
    EvidenceField,
    PaymentRequestEvidence,
    SourceReview,
    TrustedVendorRecord,
)

DESTINATION_FIELDS: tuple[EvidenceField, ...] = (
    "account_identifier",
    "routing_identifier",
    "destination_scheme",
)


class Issue(Contract):
    stage: Literal["extraction", "comparison", "orchestration"]
    code: str
    field: EvidenceField | None = None
    detail: str


class FieldScore(Contract):
    field: EvidenceField
    expected_values: int
    observed_values: int
    correct_values: int
    status_correct: bool


class Outcome(Contract):
    case_id: str
    expected: BenchmarkExpectation
    result: ComparisonResult | None
    review: SourceReview | None
    failed_operation: bool
    state_correct: bool
    reasons_correct: bool
    content_correct: bool
    destination_correct: bool
    extraction_correct: bool | None
    field_scores: tuple[FieldScore, ...] = ()
    issues: tuple[Issue, ...]

    @property
    def exact_correct(self) -> bool:
        return (
            not self.failed_operation
            and self.state_correct
            and self.reasons_correct
            and self.content_correct
            and self.extraction_correct is not False
        )


class Fraction(Contract):
    numerator: int
    denominator: int
    # Keep integer fractions, including denominator zero, rather than rounded rates.


class Metrics(Contract):
    total_cases: int
    correct_state_classifications: int
    exact_correct_cases: int
    consequential_changes: int
    consequential_changes_detected: int
    consequential_changes_missed: int
    supported_consequential_changes: int
    supported_changes_detected: int
    critical_false_unchanged: int
    critical_miss_case_ids: tuple[str, ...]
    changed_cases_abstained: int
    changed_cases_failed: int
    unchanged_cases_incorrectly_escalated: int
    supported_unchanged_cases: int
    supported_unchanged_resolved: int
    supported_unchanged_unnecessarily_escalated: int
    expected_uncertain_cases: int
    uncertain_cases_handled_correctly: int
    unsafe_definitive_on_uncertain: int
    unnecessary_abstentions: int
    uncertainty_recall: Fraction
    uncertainty_precision: Fraction
    extraction_failures: int | None
    extraction_error_cases: int | None
    deterministic_comparison_failures: int
    failed_operations: int
    confusion: dict[str, dict[str, int]]
    error_categories: dict[str, int]
    fields: dict[str, dict[str, int]]


def score_extraction(
    case: BenchmarkCase, evidence: PaymentRequestEvidence
) -> tuple[tuple[FieldScore, ...], tuple[Issue, ...]]:
    """Raw values and current roles, accepting equivalent exact quote boundaries."""
    issues: list[Issue] = []
    scores: list[FieldScore] = []
    for name in EVIDENCE_FIELDS:
        gold = getattr(case.gold_evidence, name)
        observed = getattr(evidence, name)
        wanted = {c.value for c in gold.candidates}
        actual = {c.value for c in observed.candidates}
        correct: set[str | bool] = set()
        for candidate in observed.candidates:
            span = candidate.evidence
            # The excerpt must include the correct source occurrence/role, not
            # merely a matching literal somewhere else in the document.
            matches = [
                g
                for g in gold.candidates
                if g.value == candidate.value and g.evidence.source_id == span.source_id
            ]
            for match in matches:
                gspan = match.evidence
                value_start = gspan.location.char_start + gspan.exact_excerpt.index(
                    gspan.extracted_value
                )
                if (
                    span.location.char_start <= value_start
                    and value_start + len(gspan.extracted_value) <= span.location.char_end
                ):
                    correct.add(candidate.value)
                    break
            else:
                wrong_role = any(
                    s.source_id == span.source_id and s.raw_value == candidate.value
                    for s in case.non_destination_spans
                )
                issues.append(
                    Issue(
                        stage="extraction",
                        code="WRONG_ROLE" if wrong_role else "SPURIOUS_VALUE",
                        field=name,
                        detail="Candidate lacks gold support for this field/current instruction role.",
                    )
                )
        if wanted - correct:
            issues.append(
                Issue(
                    stage="extraction",
                    code="AMBIGUITY_LOSS" if len(wanted) > 1 else "FIELD_OMISSION",
                    field=name,
                    detail="One or more distinct source-supported observations were not retained.",
                )
            )
        # Identical repeated literals can be represented once, even across sources.
        status_correct = (
            observed.status == gold.status
            if not wanted or len(wanted) > 1
            else observed.status in ("FOUND", "AMBIGUOUS") and actual == wanted
        )
        if not status_correct:
            issues.append(
                Issue(
                    stage="extraction",
                    code="STATUS_MISCLASSIFICATION",
                    field=name,
                    detail=f"Expected {gold.status}; observed {observed.status}.",
                )
            )
        scores.append(
            FieldScore(
                field=name,
                expected_values=len(wanted),
                observed_values=len(actual),
                correct_values=len(correct),
                status_correct=status_correct,
            )
        )
    return tuple(scores), tuple(issues)


def score_content(
    case: BenchmarkCase,
    baseline: TrustedVendorRecord | None,
    evidence: PaymentRequestEvidence,
    result: ComparisonResult,
    *,
    reviewed: bool,
) -> tuple[Issue, ...]:
    """Check against authored values, without running another comparator oracle."""
    issues: list[Issue] = []

    def mismatch(field: EvidenceField | None, detail: str) -> None:
        issues.append(
            Issue(
                stage="comparison", code="RESULT_EVIDENCE_INCONSISTENCY", field=field, detail=detail
            )
        )

    canonical = case.normalized_gold_requested_identity
    expected_identity = canonical if reviewed else None
    # Raw representative/IDs may differ, but full canonical identity cannot.
    actual_account = (
        result.requested_identity.account_identifier if result.requested_identity else None
    )
    expected_account = expected_identity.account_identifier if expected_identity else None
    if actual_account != expected_account:
        mismatch(
            "account_identifier", "Reviewed identity differs from the authored current identity."
        )
    if result.baseline_identity != (baseline.payment_identity if baseline else None):
        mismatch("account_identifier", "Trusted identity differs from the frozen baseline.")
    if set(result.evidence_ids) != {s.evidence_id for s in evidence.spans()}:
        mismatch(None, "Result did not retain every extracted evidence reference.")
    fields: dict[EvidenceField, str | None] = {
        "vendor_name": baseline.canonical_vendor_name if baseline else None,
        "sender_email": baseline.trusted_email if baseline else None,
        "bank_name": baseline.bank_name if baseline else None,
        "currency": baseline.currency if baseline else None,
        "account_identifier": baseline.payment_identity.account_identifier if baseline else None,
        "routing_identifier": baseline.routing_identifier if baseline else None,
        "destination_scheme": baseline.payment_identity.scheme if baseline else None,
    }
    by_field = {d.field: d for d in result.differences}
    for name, trusted in fields.items():
        gold = getattr(case.gold_evidence, name)
        values = {c.value for c in gold.candidates}
        requested = (
            (canonical.account_identifier if canonical else None)
            if name == "account_identifier"
            else next(iter(values))
            if len(values) == 1
            else None
        )
        diff = by_field.get(name)
        expected_status = (
            "UNKNOWN"
            if trusted is None or requested is None
            else "MATCH"
            if trusted == requested
            else "CHANGED"
        )
        extracted_ids = {c.evidence.evidence_id for c in getattr(evidence, name).candidates}
        if diff is None or (
            diff.baseline_value != trusted
            or diff.requested_value != requested
            or diff.status != expected_status
            or set(diff.evidence_ids) != extracted_ids
        ):
            mismatch(name, "Field difference or field-specific evidence disagrees with gold input.")
        if len(values) > 1:
            contradictions = [c for c in result.contradictions if c.field == name]
            if not contradictions or not extracted_ids.issubset(contradictions[0].evidence_ids):
                mismatch(name, "Competing values lack a complete contradiction evidence record.")
    missing = {(m.side, m.field) for m in result.missing_information}
    required_missing = {("BASELINE", "account_identifier")} if baseline is None else set()
    for name in DESTINATION_FIELDS:
        if getattr(case.gold_evidence, name).status == "UNREADABLE" or (
            name == "account_identifier"
            and case.gold_evidence.account_identifier.status == "MISSING"
        ):
            required_missing.add(("REQUEST", name))
    if not required_missing.issubset(missing):
        mismatch(None, "Missing-information records omit an authored blocker.")
    return tuple(issues)


def summarize(cases: tuple[BenchmarkCase, ...], outcomes: tuple[Outcome, ...]) -> Metrics:
    by_id = {c.case_id: c for c in cases}
    counts: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    confusion = {
        s: dict.fromkeys(("UNCHANGED", "VERIFY", "UNCERTAIN", "FAILED"), 0)
        for s in ("UNCHANGED", "VERIFY", "UNCERTAIN")
    }
    fields: dict[str, dict[str, int]] = {}
    critical: list[str] = []
    extraction_evaluated = any(o.extraction_correct is not None for o in outcomes)
    for o in outcomes:
        case = by_id[o.case_id]
        state = o.result.state if o.result is not None and not o.failed_operation else "FAILED"
        confusion[o.expected.state][state] += 1
        counts["correct_states"] += o.state_correct
        counts["exact"] += o.exact_correct
        counts["failed"] += o.failed_operation
        counts["comparison_failures"] += any(i.stage == "comparison" for i in o.issues)
        counts["extraction_failures"] += o.failed_operation and any(
            i.stage == "extraction" for i in o.issues
        )
        counts["extraction_errors"] += o.extraction_correct is False
        categories.update({f"{i.stage}:{i.code}" for i in o.issues})
        for f in o.field_scores:
            totals = fields.setdefault(
                f.field,
                dict.fromkeys(
                    (
                        "expected_values",
                        "observed_values",
                        "correct_values",
                        "status_correct",
                        "cases",
                    ),
                    0,
                ),
            )
            for key in ("expected_values", "observed_values", "correct_values"):
                totals[key] += getattr(f, key)
            totals["status_correct"] += f.status_correct
            totals["cases"] += 1
        if case.ground_truth.destination_relation == "CHANGED":
            counts["changes"] += 1
            detected = state == "VERIFY" and o.destination_correct
            counts["detected"] += detected
            counts["changed_abstained"] += state == "UNCERTAIN"
            counts["changed_failed"] += state == "FAILED"
            if state == "UNCHANGED":
                critical.append(o.case_id)
            if case.ground_truth.phase1_comparable:
                counts["supported_changes"] += 1
                counts["supported_detected"] += detected
        if case.ground_truth.destination_relation == "UNCHANGED":
            counts["false_escalations"] += state == "VERIFY"
            if case.ground_truth.phase1_comparable:
                counts["supported_unchanged"] += 1
                counts["resolved_unchanged"] += state == "UNCHANGED" and o.destination_correct
                counts["unnecessary_escalation"] += state != "UNCHANGED"
        counts["predicted_uncertain"] += state == "UNCERTAIN"
        if o.expected.state == "UNCERTAIN":
            counts["expected_uncertain"] += 1
            counts["uncertain_state_correct"] += state == "UNCERTAIN"
            counts["uncertain_correct"] += state == "UNCERTAIN" and o.destination_correct
            counts["unsafe_definitive"] += state in ("UNCHANGED", "VERIFY")
        elif case.ground_truth.phase1_comparable:
            counts["unnecessary_abstention"] += state == "UNCERTAIN"
    return Metrics(
        total_cases=len(outcomes),
        correct_state_classifications=counts["correct_states"],
        exact_correct_cases=counts["exact"],
        consequential_changes=counts["changes"],
        consequential_changes_detected=counts["detected"],
        consequential_changes_missed=counts["changes"] - counts["detected"],
        supported_consequential_changes=counts["supported_changes"],
        supported_changes_detected=counts["supported_detected"],
        critical_false_unchanged=len(critical),
        critical_miss_case_ids=tuple(critical),
        changed_cases_abstained=counts["changed_abstained"],
        changed_cases_failed=counts["changed_failed"],
        unchanged_cases_incorrectly_escalated=counts["false_escalations"],
        supported_unchanged_cases=counts["supported_unchanged"],
        supported_unchanged_resolved=counts["resolved_unchanged"],
        supported_unchanged_unnecessarily_escalated=counts["unnecessary_escalation"],
        expected_uncertain_cases=counts["expected_uncertain"],
        uncertain_cases_handled_correctly=counts["uncertain_correct"],
        unsafe_definitive_on_uncertain=counts["unsafe_definitive"],
        unnecessary_abstentions=counts["unnecessary_abstention"],
        uncertainty_recall=Fraction(
            numerator=counts["uncertain_state_correct"], denominator=counts["expected_uncertain"]
        ),
        uncertainty_precision=Fraction(
            numerator=counts["uncertain_state_correct"], denominator=counts["predicted_uncertain"]
        ),
        extraction_failures=counts["extraction_failures"] if extraction_evaluated else None,
        extraction_error_cases=counts["extraction_errors"] if extraction_evaluated else None,
        deterministic_comparison_failures=counts["comparison_failures"],
        failed_operations=counts["failed"],
        confusion=confusion,
        error_categories=dict(sorted(categories.items())),
        fields=fields,
    )
