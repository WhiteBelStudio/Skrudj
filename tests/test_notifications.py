"""Tests for moderation notifications."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from skrudj.config import Settings
from skrudj.notifications import notify_telegram_admins


class FakeBot:
    def __init__(self, failing_ids: set[int] | None = None) -> None:
        self.failing_ids = failing_ids or set()
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, *, chat_id: int, text: str) -> None:
        if chat_id in self.failing_ids:
            raise RuntimeError("simulated Telegram delivery failure")
        self.messages.append((chat_id, text))


def make_listing():
    return SimpleNamespace(
        id=42,
        title="Used book",
        category="Books",
        price=Decimal("150.00"),
        city="Belorechensk",
        seller_telegram_id=12345,
    )


@pytest.mark.asyncio
async def test_pending_listing_notifies_each_configured_admin() -> None:
    bot = FakeBot()
    settings = Settings(_env_file=None, telegram_admin_ids="222,111")

    delivered = await notify_telegram_admins(bot, make_listing(), settings)

    assert delivered == 2
    assert [chat_id for chat_id, _ in bot.messages] == [111, 222]
    assert all("ожидает модерации" in text for _, text in bot.messages)
    assert all("#42" in text and "Продавец Telegram ID: 12345" in text for _, text in bot.messages)


@pytest.mark.asyncio
async def test_notification_delivery_failure_does_not_stop_other_admins() -> None:
    bot = FakeBot(failing_ids={111})
    settings = Settings(_env_file=None, telegram_admin_ids="111,222")

    delivered = await notify_telegram_admins(bot, make_listing(), settings)

    assert delivered == 1
    assert [chat_id for chat_id, _ in bot.messages] == [222]


@pytest.mark.asyncio
async def test_no_admins_means_no_messages() -> None:
    bot = FakeBot()
    settings = Settings(_env_file=None, telegram_admin_ids="")

    delivered = await notify_telegram_admins(bot, make_listing(), settings)

    assert delivered == 0
    assert bot.messages == []
