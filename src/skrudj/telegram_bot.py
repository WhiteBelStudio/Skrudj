"""Telegram bot handlers for registration, profiles, and listing creation."""

import logging
from decimal import Decimal, InvalidOperation

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from skrudj.database import (
    create_listing,
    delete_owned_listing,
    get_user_listings,
    register_or_update_telegram_user,
    update_owned_listing,
)

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


class ListingEditForm(StatesGroup):
    """State for editing a seller-owned listing field."""

    value = State()


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

    @router.message(F.text == "📦 Мои объявления")
    async def my_listings_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        if message.from_user is None:
            await message.answer("Не удалось определить аккаунт Telegram.")
            return

        async with session_factory() as session:
            listings = await get_user_listings(session, message.from_user.id)

        if not listings:
            await message.answer("У вас пока нет объявлений.", reply_markup=MAIN_MENU)
            return

        await message.answer(f"📦 Ваши объявления: {len(listings)}")
        for listing in listings:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✏️ Изменить",
                            callback_data=f"listing_edit:{listing.id}",
                        ),
                        InlineKeyboardButton(
                            text="🗑 Удалить",
                            callback_data=f"listing_delete:{listing.id}",
                        ),
                    ]
                ]
            )
            await message.answer(
                f"#{listing.id} · {listing.title}\n"
                f"Цена: {listing.price:.2f} ₽ · {listing.city}\n"
                f"Статус: {listing.status}",
                reply_markup=keyboard,
            )

    @router.callback_query(F.data.startswith("listing_edit:"))
    async def listing_edit_start_handler(callback: CallbackQuery) -> None:
        if callback.from_user is None or callback.message is None:
            await callback.answer("Не удалось открыть объявление.", show_alert=True)
            return
        listing_id = callback.data.split(":", 1)[1]
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Название", callback_data=f"listing_field:{listing_id}:title"
                    ),
                    InlineKeyboardButton(
                        text="Категория", callback_data=f"listing_field:{listing_id}:category"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Описание", callback_data=f"listing_field:{listing_id}:description"
                    ),
                    InlineKeyboardButton(
                        text="Цена", callback_data=f"listing_field:{listing_id}:price"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="Город", callback_data=f"listing_field:{listing_id}:city"
                    )
                ],
            ]
        )
        await callback.message.answer("Что хотите изменить?", reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(F.data.startswith("listing_field:"))
    async def listing_edit_field_handler(
        callback: CallbackQuery, state: FSMContext
    ) -> None:
        if callback.from_user is None or callback.message is None:
            await callback.answer("Не удалось открыть редактирование.", show_alert=True)
            return
        _, raw_id, field = callback.data.split(":", 2)
        if field not in {"title", "category", "description", "price", "city"}:
            await callback.answer("Неизвестное поле.", show_alert=True)
            return
        async with session_factory() as session:
            listings = await get_user_listings(session, callback.from_user.id)
        if not any(item.id == int(raw_id) for item in listings):
            await callback.answer("Это объявление не найдено в вашем профиле.", show_alert=True)
            return

        await state.clear()
        await state.update_data(listing_id=int(raw_id), field=field)
        await state.set_state(ListingEditForm.value)
        prompts = {
            "title": "Введите новое название (3–120 символов).",
            "category": "Введите новую категорию (1–80 символов).",
            "description": "Введите новое описание (10–2000 символов).",
            "price": "Введите новую цену в рублях, например 1500.50.",
            "city": "Введите новый город (1–100 символов).",
        }
        await callback.message.answer(prompts[field] + "\nДля отмены отправьте /cancel.")
        await callback.answer()

    @router.message(ListingEditForm.value)
    async def listing_edit_value_handler(message: Message, state: FSMContext) -> None:
        if message.from_user is None:
            await state.clear()
            await message.answer("Не удалось определить аккаунт Telegram.")
            return
        data = await state.get_data()
        field = data["field"]
        raw_value = (message.text or "").strip()
        limits = {
            "title": (3, 120),
            "category": (1, 80),
            "description": (10, 2000),
            "city": (1, 100),
        }
        value: str | Decimal = raw_value

        if field == "price":
            try:
                price = Decimal(raw_value.replace(",", ".").replace(" ", ""))
            except InvalidOperation:
                await message.answer("Введите цену числом, например 1500 или 1500.50.")
                return
            if (
                not price.is_finite()
                or price <= 0
                or price > Decimal("9999999999.99")
                or price.as_tuple().exponent < -2
            ):
                await message.answer(
                    "Цена должна быть положительной, не больше 9 999 999 999,99 ₽ "
                    "и с максимум двумя знаками после запятой."
                )
                return
            value = price.quantize(Decimal("0.01"))
        else:
            minimum, maximum = limits[field]
            if not minimum <= len(raw_value) <= maximum:
                await message.answer(
                    f"Длина значения должна быть от {minimum} до {maximum} символов."
                )
                return

        async with session_factory() as session:
            listing = await update_owned_listing(
                session,
                listing_id=data["listing_id"],
                seller_telegram_id=message.from_user.id,
                field=field,
                value=value,
            )
        await state.clear()
        if listing is None:
            await message.answer(
                "Объявление не найдено или больше вам не принадлежит.",
                reply_markup=MAIN_MENU,
            )
            return
        await message.answer(
            f"✅ Объявление #{listing.id} обновлено и отправлено на повторную модерацию.",
            reply_markup=MAIN_MENU,
        )

    @router.callback_query(F.data.startswith("listing_delete:"))
    async def listing_delete_start_handler(callback: CallbackQuery) -> None:
        if callback.message is None:
            await callback.answer()
            return
        listing_id = callback.data.split(":", 1)[1]
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Да, удалить",
                        callback_data=f"listing_delete_confirm:{listing_id}",
                    ),
                    InlineKeyboardButton(text="Отмена", callback_data="listing_delete_cancel"),
                ]
            ]
        )
        await callback.message.answer(
            f"Удалить объявление #{listing_id}? Это действие нельзя отменить.",
            reply_markup=keyboard,
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("listing_delete_confirm:"))
    async def listing_delete_confirm_handler(callback: CallbackQuery) -> None:
        if callback.from_user is None or callback.message is None:
            await callback.answer("Не удалось удалить объявление.", show_alert=True)
            return
        try:
            listing_id = int(callback.data.split(":", 1)[1])
        except ValueError:
            await callback.answer("Некорректный номер объявления.", show_alert=True)
            return
        async with session_factory() as session:
            deleted = await delete_owned_listing(
                session, listing_id=listing_id, seller_telegram_id=callback.from_user.id
            )
        await callback.message.answer(
            "🗑 Объявление удалено."
            if deleted
            else "Объявление не найдено или не принадлежит вам.",
            reply_markup=MAIN_MENU,
        )
        await callback.answer()

    @router.callback_query(F.data == "listing_delete_cancel")
    async def listing_delete_cancel_handler(callback: CallbackQuery) -> None:
        if callback.message is not None:
            await callback.message.answer("Удаление отменено.", reply_markup=MAIN_MENU)
        await callback.answer()

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
