"""Pure Phase-1 normalization shared by contracts and the future comparator."""

import re


def canonical_iban(raw: str) -> str:
    """Validate an identity representation, not bank ownership or payment safety."""
    if not re.fullmatch(r"[A-Za-z0-9 ]+", raw):
        raise ValueError("IBAN accepts ASCII letters, digits, and grouping spaces only")
    canonical = raw.replace(" ", "").upper()
    formats = {"GB": r"GB[0-9]{2}[A-Z]{4}[0-9]{14}", "DE": r"DE[0-9]{20}"}
    if canonical[:2] not in formats:
        raise ValueError("unsupported IBAN country; Phase 1 supports GB and DE")
    if not re.fullmatch(formats[canonical[:2]], canonical):
        raise ValueError("invalid country-specific IBAN format")
    rotated = canonical[4:] + canonical[:4]
    digits = "".join(str(ord(c) - 55) if "A" <= c <= "Z" else c for c in rotated)
    if int(digits) % 97 != 1:
        raise ValueError("invalid IBAN checksum")
    return canonical
