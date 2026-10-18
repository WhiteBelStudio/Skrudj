"""Tests for seller-facing listing event notifications."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from skrudj.notifications import notify_seller_listing_event


class FakeBot:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, *, chat_id: int, text: str) -> None:
        if self.fail:
            raise RuntimeError("simulated Telegram delivery failure")
        self.messages.append((chat_id, text))


def make_listing():
    return SimpleNamespace(
        id=42,
        title="Used book",
        seller_telegram_id=12345,
        category="Books",
        price=Decimal("150.00"),
        city="Belorechensk",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ("approved", "опубликовано"),
        ("rejected", "отклонено"),
        ("sold", "проданное"),
    ],
)
async def test_seller_is_notified_about_each_listing_event(event: str, expected: str) -> None:
    bot = FakeBot()

    delivered = await notify_seller_listing_event(bot, make_listing(), event)

    assert delivered is True
    assert len(bot.messages) == 1
    chat_id, text = bot.messages[0]
    assert chat_id == 12345
    assert "#42" in text
    assert "Used book" in text
    assert expected in text


@pytest.mark.asyncio
async def test_rejection_notification_includes_reason() -> None:
    bot = FakeBot()

    delivered = await notify_seller_listing_event(
        bot, make_listing(), "rejected", reason="Недостаточно информации"
    )

    assert delivered is True
    assert "Причина: Недостаточно информации" in bot.messages[0][1]


@pytest.mark.asyncio
async def test_delivery_failure_does_not_raise() -> None:
    bot = FakeBot(fail=True)

    delivered = await notify_seller_listing_event(bot, make_listing(), "approved")

    assert delivered is False
    assert bot.messages == []


@pytest.mark.asyncio
async def test_unknown_seller_event_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported seller notification event"):
        await notify_seller_listing_event(FakeBot(), make_listing(), "unknown")
