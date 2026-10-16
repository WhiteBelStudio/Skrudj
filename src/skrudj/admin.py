"""Telegram administration commands for roles, blocks and statistics."""

import logging

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, TelegramObject

from skrudj.config import Settings
from skrudj.database import (
    get_admin_statistics,
    get_user_access,
    set_user_block,
    set_user_role,
)

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
        ]
        if level == "root":
            commands.append("/role ID user|moderator|admin — назначить роль")
        if level in {"root", "admin"}:
            await message.answer("\n".join(commands))
        else:
            await message.answer("🛠 Панель модератора\n/stats — статистика проекта")

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

    router.message.outer_middleware(AccessGuardMiddleware(session_factory, settings))
    router.callback_query.outer_middleware(AccessGuardMiddleware(session_factory, settings))
    dispatcher.include_router(router)
