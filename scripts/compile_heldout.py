"""Compile authored source annotations into canonical contracts; never predict labels.

This command only checks an existing freeze. New versions require a separately
reviewed manifest, not an overwrite of the v1 expected labels after a run.
"""

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from payproof.evaluation_contracts import HeldOutCorpus
from payproof.schemas import EVIDENCE_FIELDS

ROOT = Path(__file__).resolve().parents[1] / "benchmarks/phase2-heldout-v1"


def identifier(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, "payproof:heldout-v1:" + name))


def compile_definition(authoring: dict[str, Any]) -> HeldOutCorpus:
    """Mechanical source/offset/ID compilation. Values and labels are author supplied."""
    cases = []
    baseline_by_key = {b["key"]: b["record"] for b in authoring["baselines"]}
    for definition in authoring["cases"]:
        case_id = definition["case_id"]
        observations: dict[str, list[dict[str, Any]]] = {f: [] for f in EVIDENCE_FIELDS}
        sources, exclusions = [], []
        for source_index, source in enumerate(definition["sources"]):
            text = source["text"]
            source_id = identifier(f"{case_id}:source:{source_index}")
            sources.append(
                dict(
                    source_id=source_id,
                    kind=source["kind"],
                    text=text,
                    sha256=hashlib.sha256(text.encode()).hexdigest(),
                    captured_at="2026-10-06T08:00:00Z",
                    captured_by="heldout-label-author",
                    label=f"Held-out {case_id} synthetic source {source_index + 1}",
                )
            )
            for annotation_index, annotation in enumerate(source["observations"]):
                excerpt = annotation["excerpt"]
                if text.count(excerpt) != 1:
                    raise ValueError("Author must specify a unique exact excerpt")
                start = text.index(excerpt)
                value = annotation["value"]
                observations[annotation["field"]].append(
                    dict(
                        value=value,
                        evidence=dict(
                            evidence_id=identifier(
                                f"{case_id}:{source_index}:observation:{annotation_index}"
                            ),
                            source_id=source_id,
                            field=annotation["field"],
                            extracted_value=excerpt if isinstance(value, bool) else value,
                            exact_excerpt=excerpt,
                            location=dict(char_start=start, char_end=start + len(excerpt)),
                            extraction_status="FOUND",  # cardinality assigned below
                        ),
                    )
                )
            for annotation in source["ignored"]:
                excerpt = annotation["excerpt"]
                if text.count(excerpt) != 1:
                    raise ValueError("Excluded role must have one exact source excerpt")
                start = text.index(excerpt)
                exclusions.append(
                    dict(
                        source_id=source_id,
                        role=annotation["role"],
                        raw_value=annotation["raw_value"],
                        exact_excerpt=excerpt,
                        location=dict(char_start=start, char_end=start + len(excerpt)),
                    )
                )
        fields: dict[str, Any] = {}
        for field, candidates in observations.items():
            status = (
                "UNREADABLE"
                if field in definition["unreadable_fields"]
                else "MISSING"
                if not candidates
                else "FOUND"
                if len(candidates) == 1
                else "AMBIGUOUS"
            )
            for candidate in candidates:
                candidate["evidence"]["extraction_status"] = status
            fields[field] = dict(status=status, candidates=candidates)
        fields.update(
            request_id=identifier(f"{case_id}:request"),
            source_ids=[s["source_id"] for s in sources],
            extraction=dict(
                attempt_id=identifier(f"{case_id}:gold-attempt"),
                method="FIXTURE",
                extracted_at="2026-10-06T08:01:00Z",
                schema_version="1",
                operator_id="heldout-label-author",
            ),
        )
        baseline = baseline_by_key[definition["baseline_key"]]
        canonical = definition["normalized_account"]
        identity = (
            dict(
                normalization_version="iban-gb-de-v1",
                scheme="IBAN",
                raw_account_identifier=observations["account_identifier"][0]["value"],
                account_identifier=canonical,
            )
            if canonical
            else None
        )
        relation = definition["destination_relation"]
        cases.append(
            dict(
                case_id=case_id,
                title=definition["title"],
                coverage_bucket=(
                    "TRUE_CHANGE"
                    if relation == "CHANGED"
                    else "NO_CONSEQUENTIAL_CHANGE"
                    if relation == "UNCHANGED"
                    else "UNCERTAIN"
                ),
                tags=definition["tags"] + [definition["scenario_style"]],
                baseline_key=definition["baseline_key"],
                selected_vendor_id=baseline["vendor_id"],
                sources=sources,
                gold_evidence=fields,
                non_destination_spans=exclusions,
                normalized_gold_requested_identity=identity,
                ground_truth=dict(
                    destination_relation=relation,
                    consequential_changes=(
                        [
                            dict(
                                component=component,
                                trusted_value=baseline["payment_identity"]["account_identifier"],
                                requested_value=canonical,
                            )
                            for component in definition["consequential_components"]
                        ]
                        if relation == "CHANGED"
                        else []
                    ),
                    contextual_changes=[],
                    phase1_comparable=definition["boundary"] == "SUPPORTED",
                    boundary=definition["boundary"],
                    rationale=definition["rationale"],
                ),
                after_gold_source_review=dict(
                    state=definition["expected_state"],
                    reason_codes=definition["expected_reason_codes"],
                ),
                without_source_review=dict(
                    state="UNCERTAIN",
                    reason_codes=["REVIEW_REQUIRED"]
                    + (
                        definition["expected_reason_codes"]
                        if definition["expected_state"] == "UNCERTAIN"
                        else []
                    ),
                ),
            )
        )
    return HeldOutCorpus.model_validate_json(
        json.dumps(
            dict(
                schema_version="payproof-benchmark-design-v1",
                dataset_id="payproof-phase2-heldout-72-v1",
                evaluation_status="NOT_RUN",
                independent_label_review="PENDING",
                split="HELD_OUT_FROM_MODEL_AND_TUNING",
                rule_version="iban-gb-de-v1",
                gold_review_protocol="SIMULATED_GOLD_SOURCE_REVIEW",
                label_origin="AUTHOR_SPECIFIED_BEFORE_EXECUTION_NO_MODEL",
                tuning_policy="NO_OPTIMIZATION_ON_V1",
                baselines=authoring["baselines"],
                cases=cases,
            )
        )
    )


def main() -> int:
    authored = json.loads((ROOT / "authoring.json").read_text())
    compiled = compile_definition(authored).model_dump_json(indent=2) + "\n"
    if (ROOT / "cases.json").read_text() != compiled:
        raise ValueError("Frozen cases differ from authored annotations; do not overwrite v1")
    print("PASS: 72 authored definitions reproduce exactly; no predictor executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
