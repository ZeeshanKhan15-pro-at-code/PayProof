"""Plain CLI presentation, with JSON-escaped untrusted text and exact evidence."""

import json

from payproof.cases import candidate_identity
from payproof.instruction_safety import (
    extracted_keys,
    instruction_gate,
    observation_key,
    source_inventory,
)
from payproof.schemas import EVIDENCE_FIELDS, CaseContract


def _quoted(value: str | bool | None) -> str:
    # Escape controls and Unicode/bidi formatting instead of executing terminal escapes.
    return json.dumps(value, ensure_ascii=True)


def render_evidence(case: CaseContract) -> str:
    """Show the entire bounded source and every observation before acknowledgement."""
    case = CaseContract.model_validate(case.model_dump())
    baseline = case.baseline
    lines = ["TRUSTED VENDOR BASELINE"]
    if baseline is None:
        lines.append("No trusted baseline is available.")
    else:
        lines.extend(
            (
                f"Vendor: {_quoted(baseline.canonical_vendor_name)}",
                f"Vendor ID: {baseline.vendor_id}; baseline revision: {baseline.revision_id}",
                f"Trusted account (raw): {_quoted(baseline.payment_identity.raw_account_identifier)}",
                f"Trusted account (canonical): {_quoted(baseline.payment_identity.account_identifier)}",
                f"Trusted account ending: {baseline.payment_identity.account_identifier[-4:]}",
                f"Trusted bank: {_quoted(baseline.bank_name)}",
                f"Trusted routing: {_quoted(baseline.routing_identifier)}",
                f"Trusted currency: {_quoted(baseline.currency)}",
                f"Trusted email: {_quoted(baseline.trusted_email)}",
                f"Trusted domain: {_quoted(baseline.trusted_domain)}",
                f"Old value source: {baseline.provenance.source_kind} / {_quoted(baseline.provenance.source_reference)}",
                f"Old value provenance: {_quoted(baseline.provenance.description)}",
                f"Recorded by {_quoted(baseline.provenance.recorded_by)} at {baseline.provenance.recorded_at.isoformat()}",
                f"Last verified: {baseline.last_verified_at.isoformat()}",
                f"Trusted callback: {baseline.callback_contact.method} {_quoted(baseline.callback_contact.value)}",
                f"Callback source: {_quoted(baseline.callback_contact.provenance.source_reference)}",
            )
        )
    lines.append("\nCURRENT REQUEST SOURCES (exact text, JSON-escaped)")
    for source in case.sources:
        lines.extend(
            (
                f"Source {source.source_id}: {source.kind} {_quoted(source.label)}",
                f"Captured at {source.captured_at.isoformat()}; SHA-256 {source.sha256}",
                _quoted(source.text),
            )
        )
    inventory = source_inventory(case.sources)
    observed = extracted_keys(case.evidence)
    lines.append("\nINDEPENDENT SOURCE DESTINATION INVENTORY (lexical tripwire, not intent proof)")
    for item in inventory.observations:
        lines.extend(
            (
                f"Source {item.source_id}; {item.field}; chars [{item.char_start}, {item.char_end})",
                f"  Destination-like text: {_quoted(item.raw_value)}",
                f"  Context hint: {item.hint}; relevance remains UNKNOWN without human resolution",
                "  Observed value retained by extraction"
                if observation_key(item) in observed
                else "  NOT OBSERVED BY EXTRACTION",
                f"  Exact context [{item.context_start}, {item.context_end}): {_quoted(item.exact_context)}",
            )
        )
    if inventory.truncated:
        lines.append(
            "Inventory limit reached; completeness unresolved, comparison remains UNCERTAIN."
        )
    source_gate = instruction_gate(case.sources, case.evidence)
    if source_gate.ambiguous or source_gate.incomplete:
        lines.append(source_gate.explanation)
    if not inventory.observations:
        lines.append(
            "No lexical candidate found; this does not prove complete or unchanged instructions."
        )
    metadata = case.evidence.extraction
    lines.append(f"\nEXTRACTION: {metadata.method}; failure: {metadata.failure_code or 'none'}")
    if metadata.method == "FIXTURE":
        lines.append("Synthetic fixture extraction; no live AI call or extraction-accuracy claim.")
    if metadata.method == "AI":
        lines.append(f"Provider: {_quoted(metadata.provider)}; model: {_quoted(metadata.model)}")
    sources = {source.source_id: source for source in case.sources}
    for name in EVIDENCE_FIELDS:
        observation = getattr(case.evidence, name)
        lines.append(f"{name}: {observation.status}")
        for candidate in observation.candidates:
            span = candidate.evidence
            source = sources[span.source_id]
            location = span.location
            lines.extend(
                (
                    f"  Requested value: {_quoted(candidate.value)}",
                    f"  New value source: {source.kind} {_quoted(source.label)} / {span.source_id}",
                    f"  Evidence {span.evidence_id}; chars [{location.char_start}, {location.char_end}); page {location.page_number or 'unspecified'}",
                    f"  Exact excerpt: {_quoted(span.exact_excerpt)}",
                )
            )
    preview = candidate_identity(case.evidence)
    if preview:
        lines.append(f"\nNormalized observed account: {_quoted(preview.account_identifier)}")
        lines.append(f"Requested account ending: {preview.account_identifier[-4:]}")
    else:
        lines.append("\nNormalized observed account: unavailable; no candidate was guessed.")
    return "\n".join(lines)


def render_result(case: CaseContract) -> str:
    case = CaseContract.model_validate(case.model_dump())
    result = case.comparison
    if result is None:
        raise ValueError("result display requires a comparison")
    lines = [
        f"STATE: {result.state}",
        f"Reason codes: {', '.join(result.reason_codes)}",
        f"Comparison: {result.comparison_id}; rule: {result.rule_version}; at {result.compared_at.isoformat()}",
    ]
    explanations = {
        "UNCHANGED": "The complete supported payment destination matches the trusted baseline. This is not payment approval.",
        "VERIFY": "The payment destination changed and requires independent human verification.",
        "UNCERTAIN": "The payment destination cannot be compared safely. Resolve the listed issues and review the sources before a new comparison.",
    }
    lines.append(explanations[result.state])
    lines.append("\nFIELD DIFFERENCES (contextual changes do not select the state)")
    for difference in result.differences:
        lines.append(
            f"{difference.field}: {difference.status} | trusted {_quoted(difference.baseline_value)} -> requested {_quoted(difference.requested_value)}"
        )
        if difference.evidence_ids:
            lines.append(f"  Evidence: {', '.join(str(e) for e in difference.evidence_ids)}")
    for missing in result.missing_information:
        lines.append(f"Missing {missing.side}.{missing.field}: {_quoted(missing.explanation)}")
    for contradiction in result.contradictions:
        lines.append(
            f"Contradiction {contradiction.field}: {_quoted(contradiction.explanation)}; evidence {', '.join(str(e) for e in contradiction.evidence_ids)}"
        )
    if case.review:
        lines.append(
            f"\nSource review by {_quoted(case.review.operator_id)} at {case.review.reviewed_at.isoformat()} (instruction review, not independent verification)."
        )
    else:
        lines.append("\nSource review: not recorded.")
    if case.baseline and result.state == "VERIFY":
        contact = case.baseline.callback_contact
        lines.append(
            f"Independently check the exact new destination using the previously trusted callback: {contact.method} {_quoted(contact.value)}."
        )
    if case.verification is None:
        lines.append("No independent-verification or account-ownership record was created.")
    else:
        lines.append(
            "An explicit human independent-check confirmation is recorded for this snapshot. "
            "It does not establish account ownership or approve payment. "
            "Current revision freshness must be checked by the durable workflow."
        )
    return "\n".join(lines)
