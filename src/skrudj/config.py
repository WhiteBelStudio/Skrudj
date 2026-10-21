"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/skrudj.sqlite3"


class Settings(BaseSettings):
    """Typed settings; secrets must be provided through the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    log_level: str = "INFO"
    timezone: str = "Europe/Moscow"

    telegram_bot_token: SecretStr | None = None
    vk_group_token: SecretStr | None = None
    vk_callback_secret: SecretStr | None = None
    vk_group_id: int | None = None
    vk_confirmation_code: str | None = None
    vk_callback_host: str = "0.0.0.0"
    vk_callback_port: int = Field(default=8080, ge=1, le=65535)

    database_url: str = DEFAULT_DATABASE_URL

    telegram_admin_ids: str = ""
    vk_admin_ids: str = ""

    broadcast_dry_run: bool = True
    broadcast_batch_size: int = Field(default=20, ge=1, le=500)
    broadcast_delay_seconds: float = Field(default=1.0, ge=0, le=60)

    max_photos_per_listing: int = Field(default=5, ge=1, le=20)
    max_upload_size_mb: int = Field(default=10, ge=1, le=100)

    @field_validator("vk_group_token", "vk_callback_secret", mode="before")
    @classmethod
    def normalize_vk_secrets(cls, value: object) -> object:
        """Treat empty VK secrets as unset and trim accidental whitespace."""
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("vk_confirmation_code", mode="before")
    @classmethod
    def normalize_vk_confirmation_code(cls, value: object) -> object:
        """Treat an empty confirmation code as unset."""
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("vk_group_id", mode="before")
    @classmethod
    def validate_vk_group_id(cls, value: object) -> object:
        """Accept only positive numeric VK community IDs when configured."""
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise ValueError("VK_GROUP_ID must be a positive integer.")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("VK_GROUP_ID must be a positive integer.") from exc
        if parsed <= 0 or (isinstance(value, float) and not value.is_integer()):
            raise ValueError("VK_GROUP_ID must be a positive integer.")
        return parsed

    @field_validator("database_url", mode="before")
    @classmethod
    def use_default_database_url_when_blank(cls, value: object) -> str:
        """Avoid an invalid empty SQLAlchemy URL when DATABASE_URL is blank."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return DEFAULT_DATABASE_URL
        if not isinstance(value, str):
            raise ValueError("DATABASE_URL must be a non-empty URL string.")
        return value.strip()

    @property
    def telegram_admin_id_set(self) -> set[int]:
        """Return valid comma-separated Telegram administrator IDs."""
        return _parse_id_set(self.telegram_admin_ids)

    @property
    def vk_admin_id_set(self) -> set[int]:
        """Return valid comma-separated VK administrator IDs."""
        return _parse_id_set(self.vk_admin_ids)


def _parse_id_set(raw_value: str) -> set[int]:
    ids: set[int] = set()
    for item in raw_value.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            ids.add(int(value))
        except ValueError as exc:
            raise ValueError("Admin IDs must be comma-separated integers.") from exc
    return ids


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
