"""Telegram bot handlers for registration, profiles, and listing creation."""

import logging
from decimal import Decimal

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

from skrudj.admin import AccessGuardMiddleware, setup_admin_handlers
from skrudj.config import get_settings
from skrudj.database import (
    create_listing,
    delete_owned_listing,
    get_user_listings,
    register_or_update_telegram_user,
    update_owned_listing,
)
from skrudj.listing_validation import (
    parse_price,
    photo_metadata_from_message,
    validate_photo_count,
    validate_text_field,
)
from skrudj.notifications import notify_telegram_admins

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
    photos = State()


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
        try:
            title = validate_text_field(
                message.text, field_name="Название", minimum=3, maximum=120
            )
        except ValueError as exc:
            await message.answer(f"{exc} Попробуйте ещё раз.")
            return
        await state.update_data(title=title)
        await state.set_state(ListingForm.category)
        await message.answer("Укажите категорию товара (до 80 символов).")

    @router.message(ListingForm.category)
    async def listing_category_handler(message: Message, state: FSMContext) -> None:
        try:
            category = validate_text_field(
                message.text, field_name="Категория", minimum=1, maximum=80
            )
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await state.update_data(category=category)
        await state.set_state(ListingForm.description)
        await message.answer("Опишите товар (от 10 до 2000 символов).")

    @router.message(ListingForm.description)
    async def listing_description_handler(message: Message, state: FSMContext) -> None:
        try:
            description = validate_text_field(
                message.text, field_name="Описание", minimum=10, maximum=2000
            )
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await state.update_data(description=description)
        await state.set_state(ListingForm.price)
        await message.answer("Укажите цену в рублях, например: 1500 или 1500.50.")

    @router.message(ListingForm.price)
    async def listing_price_handler(message: Message, state: FSMContext) -> None:
        try:
            price = parse_price(message.text)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await state.update_data(price=str(price))
        await state.set_state(ListingForm.city)
        await message.answer("Укажите город, в котором находится товар (до 100 символов).")

    @router.message(ListingForm.city)
    async def listing_city_handler(message: Message, state: FSMContext) -> None:
        if message.from_user is None:
            await state.clear()
            await message.answer("Не удалось определить аккаунт Telegram.")
            return
        try:
            city = validate_text_field(
                message.text, field_name="Город", minimum=1, maximum=100
            )
        except ValueError as exc:
            await message.answer(str(exc))
            return

        await state.update_data(city=city, photos=[])
        await state.set_state(ListingForm.photos)
        await message.answer(
            "📷 Теперь отправьте фотографии товара. Поддерживаются JPG, PNG и WebP; "
            f"до {get_settings().max_photos_per_listing} фото, каждое до "
            f"{get_settings().max_upload_size_mb} МБ.\n\n"
            "Когда закончите, отправьте /done. Если фото нет — /skip."
        )

    async def finish_listing_submission(message: Message, state: FSMContext) -> None:
        if message.from_user is None:
            await state.clear()
            await message.answer("Не удалось определить аккаунт Telegram.")
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
                city=data["city"],
                photos=data.get("photos", []),
            )

        await state.clear()
        await notify_telegram_admins(message.bot, listing, get_settings())
        await message.answer(
            "✅ Объявление сохранено и отправлено на модерацию.\n\n"
            f"Номер: #{listing.id}\n"
            f"Название: {listing.title}\n"
            f"Категория: {listing.category}\n"
            f"Цена: {listing.price:.2f} ₽\n"
            f"Город: {listing.city}\n"
            f"Фотографий: {len(data.get('photos', []))}\n"
            "Публикация станет доступна после проверки модератором.",
            reply_markup=MAIN_MENU,
        )

    @router.message(ListingForm.photos, F.photo | F.document)
    async def listing_photo_handler(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        photos = data.get("photos", [])
        settings = get_settings()
        try:
            validate_photo_count(len(photos), settings.max_photos_per_listing)
            photo = photo_metadata_from_message(message)
        except ValueError as exc:
            await message.answer(str(exc))
            return

        if any(item["file_unique_id"] == photo["file_unique_id"] for item in photos):
            await message.answer("Это фото уже добавлено. Отправьте другое или /done.")
            return

        photos.append(photo)
        await state.update_data(photos=photos)
        await message.answer(
            f"✅ Фото добавлено ({len(photos)}/{settings.max_photos_per_listing}). "
            "Отправьте ещё или /done для завершения."
        )

    @router.message(ListingForm.photos, Command("done"))
    @router.message(ListingForm.photos, Command("skip"))
    async def listing_photos_finish_handler(message: Message, state: FSMContext) -> None:
        await finish_listing_submission(message, state)

    @router.message(ListingForm.photos)
    async def listing_photos_invalid_handler(message: Message) -> None:
        await message.answer(
            "На этом шаге отправьте фото как изображение или файл JPG/PNG/WebP. "
            "Завершить можно командой /done, пропустить фото — /skip."
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
        raw_value = message.text
        value: str | Decimal

        if field == "price":
            try:
                value = parse_price(raw_value)
            except ValueError as exc:
                await message.answer(str(exc))
                return
        else:
            limits = {
                "title": (3, 120),
                "category": (1, 80),
                "description": (10, 2000),
                "city": (1, 100),
            }
            minimum, maximum = limits[field]
            labels = {
                "title": "Название",
                "category": "Категория",
                "description": "Описание",
                "city": "Город",
            }
            try:
                value = validate_text_field(
                    raw_value,
                    field_name=labels[field],
                    minimum=minimum,
                    maximum=maximum,
                )
            except ValueError as exc:
                await message.answer(str(exc))
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
        await notify_telegram_admins(message.bot, listing, get_settings())
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

    settings = get_settings()
    router.message.outer_middleware(AccessGuardMiddleware(session_factory, settings))
    router.callback_query.outer_middleware(AccessGuardMiddleware(session_factory, settings))
    dispatcher.include_router(router)


async def run_telegram_bot(token: str, session_factory) -> None:
    """Start long polling and close the Telegram HTTP session on shutdown."""
    bot = Bot(token=token)
    dispatcher = Dispatcher()
    setup_telegram_handlers(dispatcher, session_factory)
    setup_admin_handlers(dispatcher, session_factory, get_settings())
    try:
        logger.info("Starting Telegram bot polling.")
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
