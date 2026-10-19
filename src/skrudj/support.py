"""Telegram support tickets, message history, and staff replies."""

import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from skrudj.admin import AccessGuardMiddleware
from skrudj.config import Settings
from skrudj.database import (
    add_support_message,
    close_support_ticket,
    create_support_ticket,
    get_open_support_tickets,
    get_support_messages,
    get_support_ticket,
    get_user_access,
    get_user_support_tickets,
    register_or_update_telegram_user,
)

logger = logging.getLogger(__name__)
router = Router(name="support")

STATUS_LABELS = {
    "open": "🟡 Открыто",
    "answered": "💬 Есть ответ",
    "closed": "🔒 Закрыто",
}


class SupportForm(StatesGroup):
    """Collect a support issue and optionally one screenshot."""

    body = State()
    attachment = State()


def _is_staff(settings: Settings, role: str) -> bool:
    return role in {"root", "admin", "moderator"}


async def _staff_role(session_factory, settings: Settings, telegram_id: int) -> str:
    if telegram_id in settings.telegram_admin_id_set:
        return "root"
    async with session_factory() as session:
        access = await get_user_access(session, telegram_id)
    if access is None or access.is_blocked:
        return "user"
    return access.role


async def _notify_staff(
    bot: Bot, settings: Settings, text: str, photo_id: str | None = None
) -> int:
    """Notify configured admins without undoing a persisted ticket on delivery errors."""
    delivered = 0
    for admin_id in sorted(settings.telegram_admin_id_set):
        try:
            await bot.send_message(chat_id=admin_id, text=text)
            if photo_id:
                await bot.send_photo(
                    chat_id=admin_id,
                    photo=photo_id,
                    caption="📎 Вложение к обращению",
                )
            delivered += 1
        except Exception:
            logger.warning(
                "Could not deliver support notification to admin %s.",
                admin_id,
                exc_info=True,
            )
    return delivered


async def _send_ticket_to_staff(
    message: Message,
    state: FSMContext,
    session_factory,
    settings: Settings,
    attachment_file_id: str | None = None,
) -> None:
    if message.from_user is None:
        await state.clear()
        await message.answer("Не удалось определить аккаунт Telegram.")
        return
    data = await state.get_data()
    body = str(data.get("support_body", "")).strip()
    async with session_factory() as session:
        await register_or_update_telegram_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name or "",
            last_name=message.from_user.last_name,
        )
        ticket = await create_support_ticket(
            session,
            user_telegram_id=message.from_user.id,
            body=body,
            attachment_file_id=attachment_file_id,
            attachment_type="photo" if attachment_file_id else None,
        )
    await state.clear()
    username = f"@{message.from_user.username}" if message.from_user.username else "не указан"
    notification = (
        f"🆘 Новое обращение в поддержку #{ticket.id}\n\n"
        f"Пользователь: {message.from_user.full_name}\n"
        f"Username: {username}\n"
        f"Telegram ID: {message.from_user.id}\n"
        f"Текст: {body}\n\n"
        f"Ответить: /support_reply {ticket.id} текст ответа\n"
        f"Закрыть: /support_close {ticket.id}"
    )
    delivered = await _notify_staff(message.bot, settings, notification, attachment_file_id)
    suffix = "" if delivered else (
        "\n\n⚠️ Не удалось доставить уведомление администрации. "
        "Обращение сохранено; команда поддержки может проверить /support_inbox."
    )
    await message.answer(
        f"✅ Обращение #{ticket.id} сохранено. Статус: открыто.\n"
        "Ответ поддержки придёт сюда в Telegram."
        + suffix
    )


@router.message(F.text == "🆘 Поддержка")
async def support_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(SupportForm.body)
    await message.answer(
        "🆘 Поддержка «Скрудж Макдак»\n\n"
        "Опишите проблему одним сообщением (от 1 до 2000 символов). "
        "Не отправляйте пароли или платёжные данные.\n\n"
        "После текста можно приложить один скриншот или отправить /skip. "
        "Для отмены — /cancel."
    )


@router.message(Command("cancel"), SupportForm.body)
@router.message(Command("cancel"), SupportForm.attachment)
async def support_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Обращение отменено. Если помощь понадобится, нажмите «🆘 Поддержка».")


@router.message(SupportForm.body)
async def support_body(message: Message, state: FSMContext) -> None:
    body = (message.text or "").strip()
    if not body or len(body) > 2000:
        await message.answer(
            "Опишите проблему текстом от 1 до 2000 символов. Для отмены — /cancel."
        )
        return
    await state.update_data(support_body=body)
    await state.set_state(SupportForm.attachment)
    await message.answer(
        "Можно приложить один скриншот как фото или отправить /skip, "
        "чтобы передать обращение без него."
    )


@router.message(SupportForm.attachment, Command("skip"))
async def support_skip_attachment(message: Message, state: FSMContext) -> None:
    await _send_ticket_to_staff(message, state, _session_factory, _settings)


@router.message(SupportForm.attachment, F.photo)
async def support_photo(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer("Не удалось получить фото. Отправьте его ещё раз или /skip.")
        return
    await _send_ticket_to_staff(
        message,
        state,
        _session_factory,
        _settings,
        attachment_file_id=message.photo[-1].file_id,
    )


@router.message(SupportForm.attachment)
async def support_attachment_fallback(message: Message) -> None:
    await message.answer("Отправьте скриншот как фото или /skip. Для отмены — /cancel.")


@router.message(Command("my_support"))
async def my_support(message: Message, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return
    async with _session_factory() as session:
        tickets = await get_user_support_tickets(session, message.from_user.id)
    if not tickets:
        await message.answer(
            "У вас пока нет обращений. Нажмите «🆘 Поддержка», чтобы создать первое."
        )
        return
    lines = ["🆘 Ваши обращения:"]
    for ticket in tickets:
        lines.append(
            f"#{ticket.id} — {STATUS_LABELS.get(ticket.status, ticket.status)} — "
            f"обновлено {ticket.updated_at:%d.%m.%Y %H:%M}"
        )
    lines.append("\nИстория: /support_history ID. Дополнение: /support_message ID текст.")
    await message.answer("\n".join(lines))


@router.message(Command("support_history"))
async def support_history(message: Message, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /support_history ID")
        return
    ticket_id = int(parts[1])
    async with _session_factory() as session:
        ticket = await get_support_ticket(session, ticket_id)
        if ticket is None:
            await message.answer("Обращение не найдено.")
            return
        role = await _staff_role(_session_factory, _settings, message.from_user.id)
        if ticket.user_telegram_id != message.from_user.id and not _is_staff(_settings, role):
            await message.answer("⛔ Это обращение принадлежит другому пользователю.")
            return
        history = await get_support_messages(session, ticket_id)
    lines = [
        f"🧾 История обращения #{ticket.id} — "
        f"{STATUS_LABELS.get(ticket.status, ticket.status)}"
    ]
    for item in history:
        if item.sender_role == "user" and item.sender_telegram_id == message.from_user.id:
            sender = "Вы"
        elif item.sender_role == "staff":
            sender = "Поддержка"
        else:
            sender = f"Пользователь {item.sender_telegram_id}"
        lines.append(f"\n{sender}: {item.body}")
        if item.attachment_file_id:
            lines.append("[В сообщении есть вложение-фото]")
    text = "\n".join(lines)
    for start in range(0, len(text), 3500):
        await message.answer(text[start:start + 3500])


@router.message(Command("support_message"))
async def support_followup(message: Message, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) != 3 or not parts[1].isdigit():
        await message.answer("Формат: /support_message ID текст сообщения")
        return
    ticket_id, body = int(parts[1]), parts[2].strip()
    if not body or len(body) > 2000:
        await message.answer("Сообщение должно содержать от 1 до 2000 символов.")
        return
    async with _session_factory() as session:
        ticket = await get_support_ticket(session, ticket_id)
        if ticket is None or ticket.user_telegram_id != message.from_user.id:
            await message.answer("Обращение не найдено.")
            return
        try:
            await add_support_message(
                session,
                ticket_id=ticket_id,
                sender_telegram_id=message.from_user.id,
                sender_role="user",
                body=body,
            )
        except ValueError as exc:
            await message.answer(str(exc))
            return
    await _notify_staff(
        message.bot,
        _settings,
        f"💬 Новое сообщение по обращению #{ticket_id}\n"
        f"Пользователь Telegram ID: {message.from_user.id}\nТекст: {body}\n\n"
        f"Ответить: /support_reply {ticket_id} текст ответа",
    )
    await message.answer(f"✅ Сообщение добавлено в обращение #{ticket_id}.")


@router.message(Command("support_inbox"))
async def support_inbox(message: Message, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return
    role = await _staff_role(_session_factory, _settings, message.from_user.id)
    if not _is_staff(_settings, role):
        await message.answer("⛔ Нет доступа к очереди поддержки.")
        return
    async with _session_factory() as session:
        tickets = await get_open_support_tickets(session, limit=30)
    if not tickets:
        await message.answer("✅ Нет открытых обращений.")
        return
    for ticket in tickets:
        await message.answer(
            f"🆘 Обращение #{ticket.id}\n"
            f"Пользователь Telegram ID: {ticket.user_telegram_id}\n"
            f"Статус: {STATUS_LABELS.get(ticket.status, ticket.status)}\n"
            f"Обновлено: {ticket.updated_at:%d.%m.%Y %H:%M}\n\n"
            f"История: /support_history {ticket.id}\n"
            f"Ответить: /support_reply {ticket.id} текст ответа\n"
            f"Закрыть: /support_close {ticket.id}"
        )


@router.message(Command("support_reply"))
async def support_reply(message: Message, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return
    role = await _staff_role(_session_factory, _settings, message.from_user.id)
    if not _is_staff(_settings, role):
        await message.answer("⛔ Нет доступа к ответам поддержки.")
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) != 3 or not parts[1].isdigit():
        await message.answer("Формат: /support_reply ID текст ответа")
        return
    ticket_id, body = int(parts[1]), parts[2].strip()
    if not body or len(body) > 2000:
        await message.answer("Ответ должен содержать от 1 до 2000 символов.")
        return
    async with _session_factory() as session:
        ticket = await get_support_ticket(session, ticket_id)
        if ticket is None:
            await message.answer("Обращение не найдено.")
            return
        try:
            await add_support_message(
                session,
                ticket_id=ticket_id,
                sender_telegram_id=message.from_user.id,
                sender_role="staff",
                body=body,
            )
        except ValueError as exc:
            await message.answer(str(exc))
            return
    try:
        await message.bot.send_message(
            chat_id=ticket.user_telegram_id,
            text=f"💬 Ответ поддержки по обращению #{ticket_id}\n\n{body}\n\n"
            f"История: /support_history {ticket_id}\n"
            f"Дополнить обращение: /support_message {ticket_id} текст",
        )
        await message.answer(f"✅ Ответ по обращению #{ticket_id} отправлен пользователю.")
    except Exception:
        logger.warning("Support reply delivery failed for ticket %s.", ticket_id, exc_info=True)
        await message.answer(
            f"⚠️ Ответ сохранён в истории обращения #{ticket_id}, "
            "но Telegram не подтвердил доставку пользователю."
        )


@router.message(Command("support_close"))
async def support_close(message: Message, state: FSMContext) -> None:
    await state.clear()
    if message.from_user is None:
        return
    role = await _staff_role(_session_factory, _settings, message.from_user.id)
    if not _is_staff(_settings, role):
        await message.answer("⛔ Нет доступа к закрытию обращений.")
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /support_close ID")
        return
    async with _session_factory() as session:
        ticket = await close_support_ticket(session, ticket_id=int(parts[1]))
    if ticket is None:
        await message.answer("Обращение не найдено или уже закрыто.")
        return
    try:
        await message.bot.send_message(
            chat_id=ticket.user_telegram_id,
            text=f"🔒 Обращение #{ticket.id} закрыто поддержкой. "
            "Если проблема осталась, создайте новое обращение через меню.",
        )
    except Exception:
        logger.warning(
            "Could not notify user about support ticket closure %s.",
            ticket.id,
            exc_info=True,
        )
    await message.answer(f"🔒 Обращение #{ticket.id} закрыто.")


_session_factory = None
_settings = None


def setup_support_handlers(dispatcher: Dispatcher, session_factory, settings: Settings) -> None:
    """Register support handlers and their access guard."""
    global _session_factory, _settings
    _session_factory = session_factory
    _settings = settings
    router.message.outer_middleware(AccessGuardMiddleware(session_factory, settings))
    dispatcher.include_router(router)
