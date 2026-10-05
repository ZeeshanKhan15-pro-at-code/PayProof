"""Source snapshot utilities. A digest binds content, never sender authenticity."""

import hashlib
import unicodedata


def source_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def account_quote_is_complete(text: str, raw: str, start: int, end: int) -> bool:
    """Reject a quoted prefix/infix of a longer payment identifier.

    This is lexical grounding, not discovery of omitted instructions or roles.
    Preserve malformed full values for normalization; never repair a substring.
    """

    def continues_token(char: str) -> bool:
        return (
            char.isalnum()
            or unicodedata.category(char).startswith("M")
            or unicodedata.category(char) == "Cf"
            or unicodedata.category(char) in ("Pc", "Pd", "Sm")
            or char in "-_\\/+*…"
        )

    # Space grouping is allowed inside raw identifiers. Outer ASCII spaces must
    # not hide a directly attached continuation at either end of the account.
    leading = len(raw) - len(raw.lstrip(" "))
    trailing = len(raw) - len(raw.rstrip(" "))
    offset = text.find(raw, start, end)
    if offset < 0 or not raw.strip(" "):
        return False
    while offset >= 0:
        token_start, token_end = offset + leading, offset + len(raw) - trailing
        if token_start > 0 and continues_token(text[token_start - 1]):
            return False
        if token_end < len(text) and continues_token(text[token_end]):
            return False
        if text.startswith("...", token_end):
            return False
        if (
            text.startswith(".", token_end)
            and token_end + 1 < len(text)
            and text[token_end + 1].isalnum()
        ):
            return False
        following = token_end
        while following < len(text) and text[following].isspace() and text[following] not in "\r\n":
            following += 1
        if following > token_end and following < len(text) and text[following].isdigit():
            return False
        offset = text.find(raw, offset + 1, end)
    return True
