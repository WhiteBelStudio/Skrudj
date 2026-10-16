"""Notifications for marketplace moderation events."""

import logging

from aiogram import Bot

from skrudj.config import Settings, get_settings
from skrudj.database import Listing

logger = logging.getLogger(__name__)


async def notify_telegram_admins(
    bot: Bot,
    listing: Listing,
    settings: Settings | None = None,
) -> int:
    """Notify configured Telegram moderators that a listing needs review.

    Delivery failures are logged per administrator and never undo a saved listing.
    Returns the number of administrators who received the notification.
    """
    config = settings or get_settings()
    admin_ids = config.telegram_admin_id_set
    if not admin_ids:
        logger.info(
            "Listing %s is pending moderation, but TELEGRAM_ADMIN_IDS is empty.",
            listing.id,
        )
        return 0

    text = (
        "🛡 Новое объявление ожидает модерации\n\n"
        f"Номер: #{listing.id}\n"
        f"Название: {listing.title}\n"
        f"Категория: {listing.category}\n"
        f"Цена: {listing.price:.2f} ₽\n"
        f"Город: {listing.city}\n"
        f"Продавец Telegram ID: {listing.seller_telegram_id}\n\n"
        "Публикация не выполнена автоматически: объявление ожидает решения модератора."
    )
    delivered = 0
    for admin_id in sorted(admin_ids):
        try:
            await bot.send_message(chat_id=admin_id, text=text)
        except Exception:
            logger.warning(
                "Could not notify Telegram moderator %s about listing %s.",
                admin_id,
                listing.id,
                exc_info=True,
            )
            continue
        delivered += 1

    logger.info(
        "Moderation notification for listing %s delivered to %s/%s Telegram admins.",
        listing.id,
        delivered,
        len(admin_ids),
    )
    return delivered
