"""Representation integrity and collision regressions; no live account assertions."""

import pytest
from examples import DE_IBAN, GB_IBAN

from payproof.normalization import (
    NormalizationError,
    canonical_currency,
    canonical_domain,
    canonical_email,
    canonical_iban,
    canonical_scheme,
    format_vendor_name,
    preserve_routing_identifier,
)


@pytest.mark.parametrize("canonical", [GB_IBAN, DE_IBAN])
@pytest.mark.parametrize("group_size", [1, 2, 3, 4, 5, 22])
@pytest.mark.parametrize("lowercase", [False, True])
def test_only_ascii_spacing_and_case_are_equivalent(canonical, group_size, lowercase):
    raw = (
        "  "
        + "  ".join(canonical[i : i + group_size] for i in range(0, len(canonical), group_size))
        + " "
    )
    if lowercase:
        raw = raw.lower()
    assert canonical_iban(raw) == canonical


REJECTED_ACCOUNTS = [
    ("", "DESTINATION_INCOMPLETE"),
    ("   ", "DESTINATION_INCOMPLETE"),
    (GB_IBAN[:-1], "DESTINATION_INCOMPLETE"),
    ("GB82WEST****5432", "DESTINATION_INCOMPLETE"),
    ("GB82WEST...5432", "DESTINATION_INCOMPLETE"),
    ("GB82WEST…5432", "DESTINATION_INCOMPLETE"),
    ("FR1420041010050500013M02606", "UNSUPPORTED_DESTINATION"),
    ("NL91ABNA0417164300", "UNSUPPORTED_DESTINATION"),
    ("12345698765432", "UNSUPPORTED_DESTINATION"),
    ("Ｇ" + GB_IBAN[1:], "DESTINATION_INVALID"),
    (GB_IBAN.replace("1", "١"), "DESTINATION_INVALID"),
    (GB_IBAN.replace("1", "１"), "DESTINATION_INVALID"),
    (GB_IBAN[:4] + "\u00a0" + GB_IBAN[4:], "DESTINATION_INVALID"),
    (GB_IBAN[:4] + "\u200b" + GB_IBAN[4:], "DESTINATION_INVALID"),
    (GB_IBAN[:4] + "\t" + GB_IBAN[4:], "DESTINATION_INVALID"),
    (GB_IBAN[:4] + "\n" + GB_IBAN[4:], "DESTINATION_INVALID"),
    (GB_IBAN[:4] + "\r" + GB_IBAN[4:], "DESTINATION_INVALID"),
    (GB_IBAN[:4] + "-" + GB_IBAN[4:], "DESTINATION_INVALID"),
    (GB_IBAN[:4] + "." + GB_IBAN[4:], "DESTINATION_INVALID"),
    (GB_IBAN[:4] + "/" + GB_IBAN[4:], "DESTINATION_INVALID"),
    (GB_IBAN + "0", "DESTINATION_INVALID"),
    (GB_IBAN[:-1] + "3", "DESTINATION_INVALID"),
    ("GB00" + GB_IBAN[4:], "DESTINATION_INVALID"),
    ("GB82W3ST12345698765432", "DESTINATION_INVALID"),
    ("DE89A70400440532013000", "DESTINATION_INVALID"),
    (" " * 257 + GB_IBAN, "DESTINATION_INVALID"),
]


@pytest.mark.parametrize("raw,reason", REJECTED_ACCOUNTS)
def test_invalid_inputs_are_classified_without_repair(raw, reason):
    with pytest.raises(NormalizationError) as caught:
        canonical_iban(raw)
    assert caught.value.reason_code == reason


@pytest.mark.parametrize(
    "normalizer,raw,expected",
    [
        (canonical_domain, " AcCoUnTs.VENDOR.Example\n", "accounts.vendor.example"),
        (canonical_email, " Accounts@VENDOR.Example ", "Accounts@vendor.example"),
        (canonical_currency, " gbp\t", "GBP"),
        (canonical_currency, "eur", "EUR"),
        (canonical_currency, "ZZZ", "ZZZ"),  # Shape validation, no registry assertion.
        (canonical_scheme, " iban ", "IBAN"),
        (format_vendor_name, "  Acme\t Widgets,\nInc. ", "Acme Widgets, Inc."),
        (format_vendor_name, "Straße & Sons", "Straße & Sons"),
        (preserve_routing_identifier, "001-23 456", "001-23 456"),
    ],
)
def test_context_normalization_is_conservative(normalizer, raw, expected):
    assert normalizer(raw) == expected


@pytest.mark.parametrize(
    "normalizer,raw",
    [
        (canonical_domain, "vendor.example."),
        (canonical_domain, "vеndor.example"),  # Cyrillic e.
        (canonical_domain, "vendor..example"),
        (canonical_domain, "https://vendor.example"),
        (canonical_email, "Accounts <accounts@vendor.example>"),
        (canonical_email, "accounts@ vendor.example"),
        (canonical_email, "accounts @vendor.example"),
        (canonical_email, "accounts@@vendor.example"),
        (canonical_email, "àccounts@vendor.example"),
        (canonical_currency, "$"),
        (canonical_currency, "£"),
        (canonical_currency, "US$"),
        (canonical_currency, "ＧＢＰ"),
        (canonical_currency, "GB P"),
        (canonical_scheme, "IＢAN"),
        (canonical_scheme, "IBAN/ACH"),
        (format_vendor_name, "\t \n"),
        (preserve_routing_identifier, "\t123456"),
    ],
)
def test_context_helpers_reject_unsupported_formats(normalizer, raw):
    with pytest.raises(ValueError):
        normalizer(raw)


def test_no_generic_punctuation_local_part_or_name_alias_equivalences():
    assert canonical_email("Accounts@vendor.example") != canonical_email("accounts@vendor.example")
    assert format_vendor_name("Acme, Inc.") != format_vendor_name("Acme Inc")
    assert format_vendor_name("Straße") != format_vendor_name("STRASSE")
    for first, second in [("00123", "123"), ("12-34", "1234"), ("ab12", "AB12")]:
        assert preserve_routing_identifier(first) != preserve_routing_identifier(second)
