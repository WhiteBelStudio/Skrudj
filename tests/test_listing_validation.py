"""Tests for marketplace listing input validation."""

from decimal import Decimal

import pytest

from skrudj.listing_validation import parse_price, validate_text_field


@pytest.mark.parametrize(
    ("raw_value", "minimum", "maximum", "expected"),
    [
        ("  Headphones  ", 3, 120, "Headphones"),
        ("Books", 1, 80, "Books"),
        ("A sufficiently detailed description.", 10, 2000, "A sufficiently detailed description."),
        (" Белореченск ", 1, 100, "Белореченск"),
    ],
)
def test_text_fields_are_trimmed(
    raw_value: str, minimum: int, maximum: int, expected: str
) -> None:
    assert (
        validate_text_field(
            raw_value, field_name="Поле", minimum=minimum, maximum=maximum
        )
        == expected
    )


@pytest.mark.parametrize(
    ("raw_value", "minimum", "maximum"),
    [
        (None, 1, 100),
        ("   ", 1, 100),
        ("ab", 3, 120),
        ("x" * 121, 3, 120),
    ],
)
def test_text_fields_reject_empty_or_out_of_range_values(
    raw_value: str | None, minimum: int, maximum: int
) -> None:
    with pytest.raises(ValueError):
        validate_text_field(
            raw_value, field_name="Название", minimum=minimum, maximum=maximum
        )


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("1500", Decimal("1500.00")),
        ("1500.5", Decimal("1500.50")),
        ("1 500,25", Decimal("1500.25")),
    ],
)
def test_price_accepts_rubles_and_normalizes_decimal_separator(
    raw_value: str, expected: Decimal
) -> None:
    assert parse_price(raw_value) == expected


@pytest.mark.parametrize(
    "raw_value",
    [
        None,
        "",
        "not-a-price",
        "NaN",
        "Infinity",
        "0",
        "-10",
        "10000000000",
        "12.345",
    ],
)
def test_price_rejects_invalid_values(raw_value: str | None) -> None:
    with pytest.raises(ValueError):
        parse_price(raw_value)
