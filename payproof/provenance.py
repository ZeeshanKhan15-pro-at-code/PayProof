"""Source snapshot utilities. A digest binds content, never sender authenticity."""

import hashlib


def source_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
