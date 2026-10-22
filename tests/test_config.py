"""Tests for configuration parsing."""

import pytest

from skrudj.config import DEFAULT_DATABASE_URL, Settings


def test_safe_defaults_enable_broadcast_dry_run() -> None:
    settings = Settings(_env_file=None)

    assert settings.broadcast_dry_run is True
    assert settings.broadcast_batch_size == 20
    assert settings.max_photos_per_listing == 5


def test_blank_database_url_uses_safe_sqlite_default() -> None:
    settings = Settings(_env_file=None, database_url="  ")

    assert settings.database_url == DEFAULT_DATABASE_URL


def test_admin_id_lists_are_parsed() -> None:
    settings = Settings(_env_file=None, telegram_admin_ids="123, 456,,")

    assert settings.telegram_admin_id_set == {123, 456}


def test_invalid_admin_id_is_rejected() -> None:
    settings = Settings(_env_file=None, vk_admin_ids="abc")

    with pytest.raises(ValueError, match="integers"):
        _ = settings.vk_admin_id_set


def test_blank_vk_secrets_are_treated_as_unset() -> None:
    settings = Settings(
        _env_file=None,
        vk_group_token="  ",
        vk_callback_secret="",
        vk_confirmation_code="  ",
    )

    assert settings.vk_group_token is None
    assert settings.vk_callback_secret is None
    assert settings.vk_confirmation_code is None


def test_vk_secrets_are_trimmed_without_being_logged() -> None:
    settings = Settings(
        _env_file=None,
        vk_group_token=" token-value ",
        vk_callback_secret=" callback-secret ",
    )

    assert settings.vk_group_token is not None
    assert settings.vk_group_token.get_secret_value() == "token-value"
    assert settings.vk_callback_secret is not None
    assert settings.vk_callback_secret.get_secret_value() == "callback-secret"
    assert "token-value" not in repr(settings)
    assert "callback-secret" not in repr(settings)


@pytest.mark.parametrize("group_id", [0, -1, "abc", True, 1.5])
def test_invalid_vk_group_id_is_rejected(group_id: object) -> None:
    with pytest.raises(ValueError, match="VK_GROUP_ID"):
        Settings(_env_file=None, vk_group_id=group_id)


def test_valid_vk_group_id_accepts_numeric_environment_value() -> None:
    settings = Settings(_env_file=None, vk_group_id="123456")

    assert settings.vk_group_id == 123456


def test_blank_telegram_proxy_is_treated_as_unset() -> None:
    settings = Settings(_env_file=None, telegram_proxy="  ")

    assert settings.telegram_proxy is None


def test_telegram_proxy_is_trimmed_and_hidden_from_repr() -> None:
    settings = Settings(
        _env_file=None,
        telegram_proxy=" socks5://user:password@proxy.example:1080 ",
    )

    assert settings.telegram_proxy is not None
    assert settings.telegram_proxy.get_secret_value() == "socks5://user:password@proxy.example:1080"
    assert "password" not in repr(settings)
