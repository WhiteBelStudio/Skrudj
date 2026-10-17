"""Validation helpers for marketplace listing fields and media."""

from decimal import Decimal, InvalidOperation
from typing import Any

from skrudj.config import get_settings

ALLOWED_IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


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


def validate_image_metadata(
    *,
    mime_type: str | None,
    size_bytes: int | None,
    max_size_bytes: int,
) -> None:
    """Reject unsupported image MIME types and files over the configured limit."""
    if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise ValueError("Поддерживаются только изображения JPG, PNG и WebP.")
    if size_bytes is None or size_bytes <= 0:
        raise ValueError("Не удалось проверить размер файла. Отправьте изображение ещё раз.")
    if size_bytes > max_size_bytes:
        raise ValueError(
            f"Изображение слишком большое. Максимальный размер — "
            f"{max_size_bytes // (1024 * 1024)} МБ."
        )


def validate_image_signature(data: bytes, expected_mime_type: str) -> None:
    """Verify image bytes match the declared JPEG, PNG, or WebP format."""
    detected_mime_type: str | None = None
    if data.startswith(bytes((255, 216, 255))):
        detected_mime_type = "image/jpeg"
    elif data.startswith(bytes((137, 80, 78, 71, 13, 10, 26, 10))):
        detected_mime_type = "image/png"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        detected_mime_type = "image/webp"

    if detected_mime_type is None or detected_mime_type != expected_mime_type:
        raise ValueError(
            "Файл не похож на заявленное изображение. Отправьте настоящий файл JPG, PNG или WebP."
        )

def validate_photo_count(current_count: int, max_count: int) -> None:
    """Ensure the next photo will not exceed the configured listing limit."""
    if current_count >= max_count:
        raise ValueError(f"Можно добавить не больше {max_count} фотографий к объявлению.")


def photo_metadata_from_message(message: Any) -> dict[str, Any]:
    """Extract and validate image metadata from an aiogram message."""
    max_size_bytes = get_settings().max_upload_size_mb * 1024 * 1024

    if message.photo:
        photo = message.photo[-1]
        validate_image_metadata(
            mime_type="image/jpeg",
            size_bytes=photo.file_size,
            max_size_bytes=max_size_bytes,
        )
        return {
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
            "mime_type": "image/jpeg",
            "size_bytes": photo.file_size,
        }

    document = message.document
    if document is None:
        raise ValueError("Отправьте фотографию JPG, PNG или WebP либо /done для завершения.")
    validate_image_metadata(
        mime_type=document.mime_type,
        size_bytes=document.file_size,
        max_size_bytes=max_size_bytes,
    )
    return {
        "file_id": document.file_id,
        "file_unique_id": document.file_unique_id,
        "mime_type": document.mime_type,
        "size_bytes": document.file_size,
    }
