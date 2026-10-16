"""Telegram bot handlers for registration, profiles, and listing creation."""

import logging
from decimal import Decimal, InvalidOperation

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from skrudj.database import create_listing, register_or_update_telegram_user

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


class ListingForm(StatesGroup):
    """Sequential form for a new marketplace listing."""

    title = State()
    category = State()
    description = State()
    price = State()
    city = State()


def _profile_text(user) -> str:
    """Format a compact profile without requesting sensitive contact details."""
    display_name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    username = f"@{user.username}" if user.username else "не указан"
    return (
        "👤 Мой профиль\n\n"
        f"Имя: {display_name or 'не указано'}\n"
        f"Telegram: {username}\n"
        f"ID: {user.telegram_id}\n\n"
        "Профиль создан автоматически по данным Telegram. "
        "Номер телефона и домашний адрес не запрашиваются."
    )


def setup_telegram_handlers(dispatcher: Dispatcher, session_factory) -> None:
    """Register handlers using the provided database session factory."""

    @router.message(CommandStart())
    async def start_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
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
            "Здесь можно искать товары и размещать объявления. Выберите действие.",
            reply_markup=MAIN_MENU,
        )

    @router.message(F.text == "👤 Мой профиль")
    async def profile_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
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

        await message.answer(_profile_text(user), reply_markup=MAIN_MENU)

    @router.message(Command("cancel"))
    async def cancel_listing_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Создание объявления отменено.", reply_markup=MAIN_MENU)

    @router.message(F.text == "➕ Разместить объявление")
    async def listing_start_handler(message: Message, state: FSMContext) -> None:
        if message.from_user is None:
            await message.answer("Не удалось определить аккаунт Telegram.")
            return
        await state.clear()
        await state.set_state(ListingForm.title)
        await message.answer(
            "➕ Создание объявления\n\nВведите название товара (от 3 до 120 символов). "
            "Для отмены отправьте /cancel."
        )

    @router.message(ListingForm.title)
    async def listing_title_handler(message: Message, state: FSMContext) -> None:
        title = (message.text or "").strip()
        if not 3 <= len(title) <= 120:
            await message.answer(
                "Название должно содержать от 3 до 120 символов. Попробуйте ещё раз."
            )
            return
        await state.update_data(title=title)
        await state.set_state(ListingForm.category)
        await message.answer("Укажите категорию товара (до 80 символов).")

    @router.message(ListingForm.category)
    async def listing_category_handler(message: Message, state: FSMContext) -> None:
        category = (message.text or "").strip()
        if not category or len(category) > 80:
            await message.answer("Категория обязательна и должна быть не длиннее 80 символов.")
            return
        await state.update_data(category=category)
        await state.set_state(ListingForm.description)
        await message.answer("Опишите товар (от 10 до 2000 символов).")

    @router.message(ListingForm.description)
    async def listing_description_handler(message: Message, state: FSMContext) -> None:
        description = (message.text or "").strip()
        if not 10 <= len(description) <= 2000:
            await message.answer("Описание должно содержать от 10 до 2000 символов.")
            return
        await state.update_data(description=description)
        await state.set_state(ListingForm.price)
        await message.answer("Укажите цену в рублях, например: 1500 или 1500.50.")

    @router.message(ListingForm.price)
    async def listing_price_handler(message: Message, state: FSMContext) -> None:
        raw_price = (message.text or "").strip().replace(",", ".").replace(" ", "")
        try:
            price = Decimal(raw_price)
        except InvalidOperation:
            await message.answer("Введите цену числом, например 1500 или 1500.50.")
            return
        if not price.is_finite() or price <= 0 or price > Decimal("9999999999.99"):
            await message.answer("Цена должна быть больше нуля и не превышать 9 999 999 999,99 ₽.")
            return
        if price.as_tuple().exponent < -2:
            await message.answer("Можно указать не больше двух знаков после запятой.")
            return
        await state.update_data(price=str(price.quantize(Decimal("0.01"))))
        await state.set_state(ListingForm.city)
        await message.answer("Укажите город, в котором находится товар (до 100 символов).")

    @router.message(ListingForm.city)
    async def listing_city_handler(message: Message, state: FSMContext) -> None:
        if message.from_user is None:
            await state.clear()
            await message.answer("Не удалось определить аккаунт Telegram.")
            return
        city = (message.text or "").strip()
        if not city or len(city) > 100:
            await message.answer("Город обязателен и должен быть не длиннее 100 символов.")
            return

        data = await state.get_data()
        async with session_factory() as session:
            await register_or_update_telegram_user(
                session,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name or "",
                last_name=message.from_user.last_name,
            )
            listing = await create_listing(
                session,
                seller_telegram_id=message.from_user.id,
                title=data["title"],
                category=data["category"],
                description=data["description"],
                price=Decimal(data["price"]),
                city=city,
            )

        await state.clear()
        await message.answer(
            "✅ Объявление сохранено и отправлено на модерацию.\n\n"
            f"Номер: #{listing.id}\n"
            f"Название: {listing.title}\n"
            f"Категория: {listing.category}\n"
            f"Цена: {listing.price:.2f} ₽\n"
            f"Город: {listing.city}\n"
            "Публикация станет доступна после проверки модератором.",
            reply_markup=MAIN_MENU,
        )

    @router.message()
    async def fallback_handler(message: Message) -> None:
        await message.answer(
            "Выберите действие в меню. Для создания объявления нажмите "
            "«➕ Разместить объявление».",
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
