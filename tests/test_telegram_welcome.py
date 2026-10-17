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
    assert "👤 Мой профиль" in button_texts
