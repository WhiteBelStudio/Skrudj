"""Telegram bot handlers for registration and profile viewing."""

import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from skrudj.database import make_session_factory, register_or_update_telegram_user

logger = logging.getLogger(__name__)

router = Router()

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛍️ Каталог"), KeyboardButton(text="➕ Разместить объявление")],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📦 Мои объявления")],
        [KeyboardButton(text="❤️ Избранное"), KeyboardButton(text="🆘 Поддержка")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие",
)


def _profile_text(user) -> str:
    """Format a compact profile without requesting sensitive contact details."""
    display_name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    username = f"@{user.username}" if user.username else "не указан"
    return (
        "👤 <b>Мой профиль</b>\n\n"
        f"Имя: {display_name or 'не указано'}\n"
        f"Telegram: {username}\n"
        f"ID: <code>{user.telegram_id}</code>\n\n"
        "Профиль создан автоматически по данным Telegram. "
        "Номер телефона и домашний адрес не запрашиваются."
    )


def setup_telegram_handlers(dispatcher: Dispatcher, session_factory) -> None:
    """Register handlers using the provided database session factory."""

    @router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        if message.from_user is None:
            await message.answer("Не удалось определить аккаунт Telegram. Попробуйте ещё раз.")
            return

        async with session_factory() as session:
            await register_or_update_telegram_user(
                session,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name or "",
                last_name=message.from_user.last_name,
            )

        await message.answer(
            "🦆 Добро пожаловать в «Скрудж Макдак»!\n\n"
            "Здесь можно будет искать товары и размещать объявления. "
            "Для начала выберите действие в меню.",
            reply_markup=MAIN_MENU,
        )

    @router.message(F.text == "👤 Мой профиль")
    async def profile_handler(message: Message) -> None:
        if message.from_user is None:
            await message.answer("Не удалось определить аккаунт Telegram.")
            return

        async with session_factory() as session:
            user = await register_or_update_telegram_user(
                session,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name or "",
                last_name=message.from_user.last_name,
            )

        await message.answer(_profile_text(user), reply_markup=MAIN_MENU, parse_mode="HTML")

    @router.message()
    async def fallback_handler(message: Message) -> None:
        await message.answer(
            "Пока доступна регистрация и просмотр профиля. Выберите «👤 Мой профиль» "
            "или воспользуйтесь меню.",
            reply_markup=MAIN_MENU,
        )

    dispatcher.include_router(router)


async def run_telegram_bot(token: str, session_factory) -> None:
    """Start long polling and close the Telegram HTTP session on shutdown."""
    bot = Bot(token=token)
    dispatcher = Dispatcher()
    setup_telegram_handlers(dispatcher, session_factory)
    try:
        logger.info("Starting Telegram bot polling.")
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
