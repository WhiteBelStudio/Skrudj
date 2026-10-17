"""Tests for marketplace listing input validation."""

from decimal import Decimal

import pytest

from skrudj.listing_validation import (
    parse_price,
    validate_image_metadata,
    validate_image_signature,
    validate_photo_count,
    validate_text_field,
)


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



@pytest.mark.parametrize("mime_type", ["image/jpeg", "image/png", "image/webp"])
def test_allowed_image_types_are_accepted(mime_type: str) -> None:
    validate_image_metadata(
        mime_type=mime_type,
        size_bytes=1024,
        max_size_bytes=10 * 1024 * 1024,
    )


@pytest.mark.parametrize(
    ("mime_type", "size_bytes"),
    [
        ("application/pdf", 1024),
        ("image/svg+xml", 1024),
        ("image/jpeg", 0),
        ("image/png", None),
        ("image/webp", 10 * 1024 * 1024 + 1),
    ],
)
def test_invalid_or_oversized_images_are_rejected(
    mime_type: str, size_bytes: int | None
) -> None:
    with pytest.raises(ValueError):
        validate_image_metadata(
            mime_type=mime_type,
            size_bytes=size_bytes,
            max_size_bytes=10 * 1024 * 1024,
        )


def test_photo_count_enforces_limit() -> None:
    validate_photo_count(4, 5)
    with pytest.raises(ValueError, match="не больше 5"):
        validate_photo_count(5, 5)



@pytest.mark.parametrize(
    ("data", "mime_type"),
    [
        (bytes((255, 216, 255)) + b"fake-jpeg-payload", "image/jpeg"),
        (bytes((137, 80, 78, 71, 13, 10, 26, 10)) + b"fake-png-payload", "image/png"),
        (b"RIFF" + bytes(4) + b"WEBP" + b"fake-webp-payload", "image/webp"),
    ],
)
def test_image_signature_matches_declared_format(data: bytes, mime_type: str) -> None:
    validate_image_signature(data, mime_type)


@pytest.mark.parametrize(
    ("data", "mime_type"),
    [
        (b"not-an-image", "image/jpeg"),
        (b"RIFF" + bytes(4) + b"WEBPpayload", "image/png"),
        (bytes((255, 216, 255)) + b"payload", "image/webp"),
        (b"", "image/png"),
    ],
)
def test_image_signature_rejects_mismatched_or_invalid_content(
    data: bytes, mime_type: str
) -> None:
    with pytest.raises(ValueError, match="не похоже"):
        validate_image_signature(data, mime_type)
