"""Reserved pure comparator boundary; implement the frozen decision table next."""

from payproof.schemas import CaseContract, ComparisonResult


def compare(case: CaseContract) -> ComparisonResult:
    raise NotImplementedError("Deterministic comparison engine is not implemented")
