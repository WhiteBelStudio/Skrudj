"""Tests for configuration parsing."""

import pytest

from skrudj.config import Settings


def test_safe_defaults_enable_broadcast_dry_run() -> None:
    settings = Settings(_env_file=None)

    assert settings.broadcast_dry_run is True
    assert settings.broadcast_batch_size == 20
    assert settings.max_photos_per_listing == 5


def test_admin_id_lists_are_parsed() -> None:
    settings = Settings(_env_file=None, telegram_admin_ids="123, 456,,")

    assert settings.telegram_admin_id_set == {123, 456}


def test_invalid_admin_id_is_rejected() -> None:
    settings = Settings(_env_file=None, vk_admin_ids="abc")

    with pytest.raises(ValueError, match="integers"):
        _ = settings.vk_admin_id_set
