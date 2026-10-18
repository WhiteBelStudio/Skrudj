"""Telegram administration commands for roles, blocks and statistics."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, TelegramObject

from skrudj.config import Settings
from skrudj.database import (
    get_admin_statistics,
    get_pending_listing_reports,
    resolve_listing_report,
    get_user_access,
    mark_listing_sold,
    moderate_listing,
    set_user_block,
    set_user_role,
)
from skrudj.notifications import notify_seller_listing_event

logger = logging.getLogger(__name__)
router = Router()

class AccessGuardMiddleware(BaseMiddleware):
    """Stop blocked accounts from interacting with the bot."""

    def __init__(self, session_factory, settings: Settings) -> None:
        self.session_factory = session_factory
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None or user.id in self.settings.telegram_admin_id_set:
            return await handler(event, data)

        async with self.session_factory() as session:
            access = await get_user_access(session, user.id)
        if access is None or not access.is_blocked:
            return await handler(event, data)

        reason = f" Причина: {access.block_reason}" if access.block_reason else ""
        notice = f"🚫 Доступ к Skrudj ограничен.{reason}"
        if isinstance(event, CallbackQuery):
            await event.answer(notice, show_alert=True)
        elif isinstance(event, Message):
            await event.answer(notice)
        return None


ROLE_LABELS = {
    "user": "Пользователь",
    "moderator": "Модератор",
    "admin": "Администратор",
}


def _parse_target_id(raw_value: str) -> int:
    try:
        target_id = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("ID должен быть целым числом Telegram.") from exc
    if target_id <= 0:
        raise ValueError("ID должен быть положительным числом.")
    return target_id


async def _access_level(session_factory, telegram_id: int, settings: Settings) -> str:
    if telegram_id in settings.telegram_admin_id_set:
        return "root"
    async with session_factory() as session:
        access = await get_user_access(session, telegram_id)
    return access.role if access and not access.is_blocked else "user"


def setup_admin_handlers(dispatcher, session_factory, settings: Settings) -> None:
    """Register admin commands with explicit role checks."""

    @router.message(Command("admin"))
    async def admin_help(message: Message) -> None:
        if message.from_user is None:
            return
        level = await _access_level(session_factory, message.from_user.id, settings)
        if level == "user":
            await message.answer("⛔ Нет доступа к панели администрирования.")
            return
        commands = [
            "🛠 Панель Skrudj",
            "/stats — статистика проекта",
            "/block ID причина — заблокировать пользователя",
            "/unblock ID — снять блокировку",
            "/approve ID — одобрить объявление",
            "/reject ID причина — отклонить объявление",
            "/sold ID — отметить объявление проданным",
        ]
        if level == "root":
            commands.append("/role ID user|moderator|admin — назначить роль")
        if level in {"root", "admin"}:
            await message.answer("\n".join(commands))
        else:
            await message.answer(
                "🛠 Панель модератора\n"
                "/stats — статистика проекта\n"
                "/approve ID — одобрить объявление\n"
                "/reject ID причина — отклонить объявление\n"
                "/sold ID — отметить объявление проданным"
            )

    @router.message(Command("stats"))
    async def stats_handler(message: Message) -> None:
        if message.from_user is None:
            return
        level = await _access_level(session_factory, message.from_user.id, settings)
        if level not in {"root", "admin", "moderator"}:
            await message.answer("⛔ Недостаточно прав.")
            return
        async with session_factory() as session:
            stats = await get_admin_statistics(session)
        await message.answer(
            "📊 Статистика Skrudj\n\n"
            f"Пользователей: {stats['users']}\n"
            f"Всего объявлений: {stats['listings']}\n"
            f"Ожидают модерации: {stats['pending_listings']}\n"
            f"Опубликовано: {stats['published_listings']}\n"
            f"Заблокировано пользователей: {stats['blocked_users']}\n"
            f"Сотрудников (модераторы/администраторы): {stats['staff']}"
        )

    @router.message(Command("role"))
    async def role_handler(message: Message) -> None:
        if message.from_user is None:
            return
        if message.from_user.id not in settings.telegram_admin_id_set:
            await message.answer("⛔ Назначать роли может только владелец из TELEGRAM_ADMIN_IDS.")
            return
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) != 3:
            await message.answer("Формат: /role ID user|moderator|admin")
            return
        try:
            target_id = _parse_target_id(parts[1])
        except ValueError as exc:
            await message.answer(str(exc))
            return
        role = parts[2].strip().lower()
        if role not in ROLE_LABELS:
            await message.answer("Роль должна быть: user, moderator или admin.")
            return
        if target_id in settings.telegram_admin_id_set and role != "admin":
            await message.answer("Нельзя понизить владельца, заданного в TELEGRAM_ADMIN_IDS.")
            return
        async with session_factory() as session:
            access = await set_user_role(session, telegram_id=target_id, role=role)
        await message.answer(
            f"✅ Роль для Telegram ID {target_id}: {ROLE_LABELS[access.role]}."
        )

    @router.message(Command("block"))
    async def block_handler(message: Message) -> None:
        if message.from_user is None:
            return
        level = await _access_level(session_factory, message.from_user.id, settings)
        if level not in {"root", "admin"}:
            await message.answer("⛔ Блокировать пользователей могут только администраторы.")
            return
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 2:
            await message.answer("Формат: /block ID причина")
            return
        try:
            target_id = _parse_target_id(parts[1])
        except ValueError as exc:
            await message.answer(str(exc))
            return
        if target_id in settings.telegram_admin_id_set:
            await message.answer("Нельзя заблокировать владельца из TELEGRAM_ADMIN_IDS.")
            return
        if target_id == message.from_user.id:
            await message.answer("Нельзя заблокировать самого себя.")
            return
        async with session_factory() as session:
            await set_user_block(
                session,
                telegram_id=target_id,
                blocked=True,
                reason=parts[2] if len(parts) > 2 else None,
            )
        await message.answer(f"🚫 Пользователь {target_id} заблокирован.")

    @router.message(Command("unblock"))
    async def unblock_handler(message: Message) -> None:
        if message.from_user is None:
            return
        level = await _access_level(session_factory, message.from_user.id, settings)
        if level not in {"root", "admin"}:
            await message.answer("⛔ Снимать блокировки могут только администраторы.")
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("Формат: /unblock ID")
            return
        try:
            target_id = _parse_target_id(parts[1])
        except ValueError as exc:
            await message.answer(str(exc))
            return
        async with session_factory() as session:
            await set_user_block(session, telegram_id=target_id, blocked=False)
        await message.answer(f"✅ Блокировка пользователя {target_id} снята.")


    @router.message(Command("approve"))
    async def approve_listing_handler(message: Message) -> None:
        if message.from_user is None:
            return
        level = await _access_level(session_factory, message.from_user.id, settings)
        if level not in {"root", "admin", "moderator"}:
            await message.answer("⛔ Недостаточно прав для модерации объявлений.")
            return
        parts = (message.text or "").split()
        if len(parts) != 2:
            await message.answer("Формат: /approve ID")
            return
        try:
            listing_id = _parse_target_id(parts[1])
        except ValueError as exc:
            await message.answer(str(exc))
            return
        async with session_factory() as session:
            listing = await moderate_listing(session, listing_id=listing_id, decision="approve")
        if listing is None:
            await message.answer("Объявление не найдено или уже не ожидает модерации.")
            return
        notified = await notify_seller_listing_event(message.bot, listing, "approved")
        suffix = "" if notified else " Уведомление продавцу отправить не удалось."
        await message.answer(f"✅ Объявление #{listing.id} опубликовано.{suffix}")

    @router.message(Command("reject"))
    async def reject_listing_handler(message: Message) -> None:
        if message.from_user is None:
            return
        level = await _access_level(session_factory, message.from_user.id, settings)
        if level not in {"root", "admin", "moderator"}:
            await message.answer("⛔ Недостаточно прав для модерации объявлений.")
            return
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3 or not parts[2].strip():
            await message.answer("Формат: /reject ID причина отклонения")
            return
        try:
            listing_id = _parse_target_id(parts[1])
        except ValueError as exc:
            await message.answer(str(exc))
            return
        reason = parts[2].strip()[:500]
        async with session_factory() as session:
            listing = await moderate_listing(session, listing_id=listing_id, decision="reject")
        if listing is None:
            await message.answer("Объявление не найдено или уже не ожидает модерации.")
            return
        notified = await notify_seller_listing_event(
            message.bot, listing, "rejected", reason=reason
        )
        suffix = "" if notified else " Уведомление продавцу отправить не удалось."
        await message.answer(f"🔴 Объявление #{listing.id} отклонено.{suffix}")

    @router.message(Command("sold"))
    async def sold_listing_handler(message: Message) -> None:
        if message.from_user is None:
            return
        level = await _access_level(session_factory, message.from_user.id, settings)
        if level not in {"root", "admin", "moderator"}:
            await message.answer("⛔ Недостаточно прав для изменения статуса объявления.")
            return
        parts = (message.text or "").split()
        if len(parts) != 2:
            await message.answer("Формат: /sold ID")
            return
        try:
            listing_id = _parse_target_id(parts[1])
        except ValueError as exc:
            await message.answer(str(exc))
            return
        async with session_factory() as session:
            listing = await mark_listing_sold(session, listing_id=listing_id)
        if listing is None:
            await message.answer("Объявление не найдено или не опубликовано.")
            return
        notified = await notify_seller_listing_event(message.bot, listing, "sold")
        suffix = "" if notified else " Уведомление продавцу отправить не удалось."
        await message.answer(f"🎉 Объявление #{listing.id} отмечено как проданное.{suffix}")



    @router.message(Command("reports"))
    async def reports_handler(message: Message) -> None:
        if message.from_user is None:
            return
        level = await _access_level(session_factory, message.from_user.id, settings)
        if level not in {"root", "admin", "moderator"}:
            await message.answer("⛔ Недостаточно прав для просмотра жалоб.")
            return
        async with session_factory() as session:
            reports = await get_pending_listing_reports(session, limit=20)
        if not reports:
            await message.answer("✅ Ожидающих жалоб нет.")
            return
        for report in reports:
            await message.answer(
                f"🚩 Жалоба #{report.id} на объявление #{report.listing_id}\n"
                f"От пользователя: {report.reporter_telegram_id}\n"
                f"Причина: {report.reason}\n"
                f"/reportdone {report.id} — отметить проверенной"
            )

    @router.message(Command("reportdone"))
    async def report_done_handler(message: Message) -> None:
        if message.from_user is None:
            return
        level = await _access_level(session_factory, message.from_user.id, settings)
        if level not in {"root", "admin", "moderator"}:
            await message.answer("⛔ Недостаточно прав.")
            return
        parts = (message.text or "").split()
        if len(parts) != 2:
            await message.answer("Формат: /reportdone ID")
            return
        try:
            report_id = _parse_target_id(parts[1])
        except ValueError as exc:
            await message.answer(str(exc))
            return
        async with session_factory() as session:
            report = await resolve_listing_report(session, report_id=report_id)
        if report is None:
            await message.answer("Жалоба не найдена или уже проверена.")
            return
        await message.answer(f"✅ Жалоба #{report.id} отмечена проверенной.")

    router.message.outer_middleware(AccessGuardMiddleware(session_factory, settings))
    router.callback_query.outer_middleware(AccessGuardMiddleware(session_factory, settings))
    dispatcher.include_router(router)
