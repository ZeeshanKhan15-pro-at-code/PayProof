"""Pure, conservative normalization; destination equality supports GB/DE IBAN only."""

import re
from typing import Literal

NormalizationReason = Literal[
    "DESTINATION_INCOMPLETE", "UNSUPPORTED_DESTINATION", "DESTINATION_INVALID"
]


class NormalizationError(ValueError):
    """A rejected destination representation, never a fraud determination."""

    def __init__(self, reason_code: NormalizationReason, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


def canonical_iban(raw: str) -> str:
    """Validate an identity representation, not bank ownership or payment safety."""
    if len(raw) > 256:
        raise NormalizationError("DESTINATION_INVALID", "IBAN input exceeds representation limit")
    if not raw.replace(" ", "") or any(marker in raw for marker in ("*", "...", "…")):
        raise NormalizationError("DESTINATION_INCOMPLETE", "IBAN is empty, masked, or truncated")
    if not re.fullmatch(r"[A-Za-z0-9 ]+", raw):
        raise NormalizationError(
            "DESTINATION_INVALID", "IBAN accepts ASCII letters, digits, and grouping spaces only"
        )
    canonical = raw.replace(" ", "").upper()
    formats = {"GB": r"GB[0-9]{2}[A-Z]{4}[0-9]{14}", "DE": r"DE[0-9]{20}"}
    if canonical[:2] not in formats:
        raise NormalizationError(
            "UNSUPPORTED_DESTINATION", "unsupported IBAN country; Phase 1 supports GB and DE"
        )
    if len(canonical) < 22:
        raise NormalizationError("DESTINATION_INCOMPLETE", "IBAN is shorter than country format")
    if not re.fullmatch(formats[canonical[:2]], canonical):
        raise NormalizationError("DESTINATION_INVALID", "invalid country-specific IBAN format")
    rotated = canonical[4:] + canonical[:4]
    digits = "".join(str(ord(c) - 55) if "A" <= c <= "Z" else c for c in rotated)
    if int(digits) % 97 != 1:
        raise NormalizationError("DESTINATION_INVALID", "invalid IBAN checksum")
    return canonical


def canonical_scheme(raw: str) -> str:
    """Normalize an ASCII scheme label, without mapping aliases to IBAN."""
    value = raw.strip(" ")
    if not re.fullmatch(r"[A-Za-z]+", value):
        raise ValueError("scheme label must contain ASCII letters")
    return value.upper()


def preserve_routing_identifier(raw: str) -> str:
    """No scheme-specific routing equivalences are supported; preserve every character."""
    if not raw.strip() or len(raw) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in raw):
        raise ValueError("routing identifier must be bounded, nonblank text without controls")
    return raw


def canonical_domain(raw: str) -> str:
    """ASCII DNS casing only; no Unicode conversion, trailing-dot removal, or aliasing."""
    value = raw.strip(" \t\r\n")
    if len(value) > 253 or not re.fullmatch(
        r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", value
    ):
        raise ValueError("unsupported domain representation")
    return value.lower()


def canonical_email(raw: str) -> str:
    """Preserve potentially case-sensitive local parts and normalize only the domain."""
    value = raw.strip(" \t\r\n")
    if len(value) > 254 or value.count("@") != 1:
        raise ValueError("unsupported email representation")
    local, domain = value.split("@")
    if domain != domain.strip(" \t\r\n"):
        raise ValueError("email cannot contain whitespace around the domain")
    if not re.fullmatch(
        r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*", local
    ):
        raise ValueError("unsupported email local part")
    return f"{local}@{canonical_domain(domain)}"


def canonical_currency(raw: str) -> str:
    """Normalize three ASCII letters; ambiguous symbols/aliases are rejected."""
    value = raw.strip(" \t\r\n")
    if not re.fullmatch(r"[A-Za-z]{3}", value):
        raise ValueError("currency must be a three-letter ASCII code")
    return value.upper()


def format_vendor_name(raw: str) -> str:
    """Display formatting only: collapse ASCII whitespace, retaining case/punctuation."""
    value = re.sub(r"[ \t\r\n]+", " ", raw).strip(" ")
    if not value.strip() or len(value) > 256:
        raise ValueError("vendor name must be bounded nonblank text")
    return value
