"""Tests for Telegram welcome, rules, help, and main menu."""

from skrudj.telegram_bot import HELP_TEXT, MAIN_MENU, RULES_TEXT, WELCOME_TEXT


def test_welcome_explains_marketplace_and_moderation() -> None:
    assert "Скрудж Макдак" in WELCOME_TEXT
    assert "размещать" in WELCOME_TEXT
    assert "модерацию" in WELCOME_TEXT
    assert "📜 Правила" in WELCOME_TEXT


def test_rules_cover_truthful_listings_privacy_and_complaints() -> None:
    assert "достоверные объявления" in RULES_TEXT
    assert "личные данные" in RULES_TEXT
    assert "поддержку" in RULES_TEXT
    assert "модерацию" in RULES_TEXT


def test_help_lists_supported_basic_commands() -> None:
    assert "/start" in HELP_TEXT
    assert "/rules" in HELP_TEXT
    assert "/help" in HELP_TEXT
    assert "/cancel" in HELP_TEXT


def test_main_menu_exposes_rules_and_help() -> None:
    button_texts = {
        button.text
        for row in MAIN_MENU.keyboard
        for button in row
    }

    assert "📜 Правила" in button_texts
    assert "ℹ️ Помощь" in button_texts
    assert "➕ Разместить объявление" in button_texts
    assert "🛍️ Каталог" in button_texts
    assert "👤 Мой профиль" in button_texts


def test_seller_profile_shows_listing_statistics_without_private_contact_fields() -> None:
    from types import SimpleNamespace

    from skrudj.telegram_bot import _profile_text

    user = SimpleNamespace(
        first_name="Alex",
        last_name="Seller",
        username="alex_seller",
        telegram_id=123456,
    )
    profile = _profile_text(
        user,
        {"total": 4, "pending": 1, "published": 2, "rejected": 1},
    )

    assert "Профиль продавца" in profile
    assert "Всего: 4" in profile
    assert "На модерации: 1" in profile
    assert "Опубликовано: 2" in profile
    assert "Отклонено: 1" in profile
    assert "@alex_seller" in profile
    assert "Номер телефона и домашний адрес не запрашиваются" in profile
