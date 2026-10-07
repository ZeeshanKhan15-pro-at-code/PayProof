"""Conservative source inventory, independent of extraction and trusted baselines.

This is a bounded lexical tripwire, not an exhaustive payment parser or an
instruction-role oracle. Context hints never authorize discarding a candidate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from payproof.normalization import NormalizationError, canonical_iban

if TYPE_CHECKING:
    from payproof.schemas import PaymentRequestEvidence, SourceDocument

MAX_OBSERVATIONS = 256
_COMPACT = re.compile(r"(?<!\w)[^\W\d_]{2}[\d*]{2}[^\s.,;:!?()<>\[\]{}\"']{8,64}")
# Discovery tolerates suspicious separators so an extractor cannot hide a
# competing identifier by omitting it. Identity normalization is unchanged:
# Unicode/control characters remain invalid and must never be repaired.
_SEPARATOR = r"[\s\u00a0\u1680\u2000-\u200f\u2028-\u202f\u205f\u2060-\u206f\u3000\ufeff]*"
# GB/DE-shaped structures, including suspicious Unicode letters/digits. Detection
# does not identify a country or repair a value; canonical_iban still rejects
# unsupported characters. Fixed structure lengths avoid consuming adjacent prose.
_LETTER = r"[^\W\d_]"
_GROUPED = re.compile(
    rf"(?<!\w)(?:{_LETTER}{_SEPARATOR}{_LETTER}"
    rf"(?:{_SEPARATOR}\d){{2}}(?:{_SEPARATOR}{_LETTER}){{4}}"
    rf"(?:{_SEPARATOR}\d){{14}}|{_LETTER}{_SEPARATOR}{_LETTER}"
    rf"(?:{_SEPARATOR}\d){{20}})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_LABEL = re.compile(
    r"\b(?:IBAN|routing(?:\s+(?:number|identifier))?|sort\s+code|wallet|"
    r"remit(?:\s+to)?|send\s+(?:funds|payment)(?:\s+to)?|pay\s+(?:to|into|via)|"
    r"account\s+(?:number|identifier)|account(?=\s*(?:[:=#]|was\b|is\b|ending\b)))\b",
    re.IGNORECASE | re.ASCII,
)
_HISTORICAL = re.compile(
    r"\b(?:old|previous|prior|historical|retired|obsolete|canceled|cancelled|archive|past)\b",
    re.IGNORECASE | re.ASCII,
)
_CURRENT = re.compile(
    r"\b(?:current|latest|new|replacement|now|pay|remit)\b", re.IGNORECASE | re.ASCII
)


@dataclass(frozen=True)
class SourceDestination:
    source_id: UUID
    field: Literal["account_identifier", "routing_identifier"]
    raw_value: str
    char_start: int
    char_end: int
    context_start: int
    context_end: int
    exact_context: str
    canonical_account: str | None
    hint: Literal["HISTORICAL_WORDING", "CURRENT_WORDING", "QUOTED_CONTEXT", "UNKNOWN"]


@dataclass(frozen=True)
class InstructionInventory:
    observations: tuple[SourceDestination, ...]
    truncated: bool


@dataclass(frozen=True)
class InstructionGate:
    ambiguous: bool
    incomplete: bool
    explanation: str


def _identity(raw: str) -> str | None:
    try:
        return canonical_iban(raw)
    except NormalizationError:
        return None


def observation_key(observation: SourceDestination) -> tuple[str, str]:
    return observation.field, observation.canonical_account or observation.raw_value


def extracted_keys(evidence: PaymentRequestEvidence) -> set[tuple[str, str]]:
    return {
        (field, (_identity(c.value) or c.value) if field == "account_identifier" else c.value)
        for field in ("account_identifier", "routing_identifier")
        for c in getattr(evidence, field).candidates
    }


def source_inventory(sources: tuple[SourceDocument, ...]) -> InstructionInventory:
    found: list[SourceDestination] = []
    for source in sources:
        text = source.text
        ranges: list[tuple[int, int, Literal["account_identifier", "routing_identifier"]]] = []
        # Longest overlapping token wins; never inventory a valid prefix in place
        # of a longer malformed token. Grouping is retained exactly, not repaired.
        matches = sorted(
            [
                (m.start(), m.end())
                for pattern in (_COMPACT, _GROUPED)
                for m in pattern.finditer(text)
            ],
            key=lambda interval: (interval[0], -interval[1]),
        )
        for start, end in matches:
            if ranges and start < ranges[-1][1]:
                continue
            ranges.append((start, end, "account_identifier"))
        for label in _LABEL.finditer(text):
            line_start = text.rfind("\n", 0, label.start()) + 1
            if re.search(
                r"\b(?:destination[_ -])?scheme\s*[:=]\s*$",
                text[line_start : label.start()],
                re.IGNORECASE | re.ASCII,
            ):
                continue  # A scheme label is not another account/value region.
            end = text.find("\n", label.end())
            end = len(text) if end < 0 else end
            # An explicit label with no recognized value is still a review region.
            # Include the next line for ordinary label/value layout, bounded to 256.
            if not text[label.end() : end].strip(" \t:=#"):
                following = text.find("\n", end + 1)
                end = len(text) if following < 0 else following
            end = min(end, label.end() + 256)
            field: Literal["account_identifier", "routing_identifier"] = (
                "routing_identifier"
                if label.group().lower().startswith(("routing", "sort"))
                else "account_identifier"
            )
            if any(field == f and label.end() <= a < end for a, _, f in ranges):
                continue
            start = label.end()
            while start < end and text[start] in " \t:=#":
                start += 1
            if start == end:
                # Retain the label itself if a value is absent, without inventing one.
                start = label.start()
            ranges.append((start, end, field))
        for start, end, field in sorted(set(ranges)):
            if len(found) == MAX_OBSERVATIONS:
                return InstructionInventory(tuple(found), True)
            raw = text[start:end]
            context_start = max(0, start - 160)
            context_end = min(len(text), end + 160)
            left = text[max(0, start - 160) : start]
            # Use the closest clause. Surrounding context remains visible regardless.
            clause = re.split(r"[.;\n]", left)[-1]
            if not clause.strip():
                clause = left
            historical, current = bool(_HISTORICAL.search(clause)), bool(_CURRENT.search(clause))
            hint: Literal["HISTORICAL_WORDING", "CURRENT_WORDING", "QUOTED_CONTEXT", "UNKNOWN"]
            if historical and not current:
                hint = "HISTORICAL_WORDING"
            elif current and not historical:
                hint = "CURRENT_WORDING"
            elif re.search(r"(?:^|\n)\s*>|forwarded message|quoted", left, re.IGNORECASE):
                hint = "QUOTED_CONTEXT"
            else:
                hint = "UNKNOWN"
            found.append(
                SourceDestination(
                    source_id=source.source_id,
                    field=field,
                    raw_value=raw,
                    char_start=start,
                    char_end=end,
                    context_start=context_start,
                    context_end=context_end,
                    exact_context=text[context_start:context_end],
                    canonical_account=_identity(raw) if field == "account_identifier" else None,
                    hint=hint,
                )
            )
    return InstructionInventory(tuple(found), False)


def instruction_gate(
    sources: tuple[SourceDocument, ...], evidence: PaymentRequestEvidence
) -> InstructionGate:
    # Independent gate adds protection where the existing observations could
    # otherwise resolve to one complete account. Invalid/missing/ambiguous
    # extracted identities already fail closed; avoid inventing redundant reasons.
    identities = [_identity(c.value) for c in evidence.account_identifier.candidates]
    if not identities or None in identities or len(set(identities)) != 1:
        return InstructionGate(False, False, "Existing destination observations are unresolved.")
    inventory = source_inventory(sources)
    observed = extracted_keys(evidence)
    account_keys = {
        observation_key(o) for o in inventory.observations if o.field == "account_identifier"
    }
    omitted = {observation_key(o) for o in inventory.observations} - observed
    ambiguous = len(account_keys) > 1
    # Missing extraction already fails closed. Add an independent blocker when
    # any destination is observed but lexical evidence is unaccounted for, solely
    # historical/quoted, or the bounded inventory cannot establish coverage.
    historical_only = bool(inventory.observations) and all(
        o.hint in ("HISTORICAL_WORDING", "QUOTED_CONTEXT") for o in inventory.observations
    )
    incomplete = (
        inventory.truncated
        or bool(observed)
        and (bool(omitted) or not account_keys or historical_only)
    )
    return InstructionGate(
        ambiguous=ambiguous,
        incomplete=incomplete and not ambiguous,
        explanation=(
            "Independent source inventory cannot establish complete current instructions. "
            "Competing, unobserved, reference-only or excess destination-like regions require "
            "resolution from the original sources; a broad review acknowledgement cannot clear this gate."
        ),
    )
