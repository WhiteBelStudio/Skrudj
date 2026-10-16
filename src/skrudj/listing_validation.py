"""Validation helpers for user-submitted marketplace listing fields."""

from decimal import Decimal, InvalidOperation


def validate_text_field(
    raw_value: str | None,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> str:
    """Trim and validate a required text field, raising a user-safe message."""
    value = (raw_value or "").strip()
    if not minimum <= len(value) <= maximum:
        raise ValueError(
            f"{field_name} должен содержать от {minimum} до {maximum} символов."
        )
    return value


def parse_price(raw_value: str | None) -> Decimal:
    """Parse a positive RUB price with at most two decimal places."""
    normalized = (raw_value or "").strip().replace(",", ".").replace(" ", "")
    try:
        price = Decimal(normalized)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Введите цену числом, например 1500 или 1500.50.") from exc

    if not price.is_finite() or price <= 0 or price > Decimal("9999999999.99"):
        raise ValueError("Цена должна быть больше нуля и не превышать 9 999 999 999,99 ₽.")
    if price.as_tuple().exponent < -2:
        raise ValueError("Можно указать не больше двух знаков после запятой.")
    return price.quantize(Decimal("0.01"))
