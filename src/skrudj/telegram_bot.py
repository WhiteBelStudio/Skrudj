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
    get_listing_photos,
    get_seller_statistics,
    get_user_favorite_listings,
    toggle_favorite,
    create_listing_report,
    get_user_listings,
    register_or_update_telegram_user,
    search_published_listings,
    unpublish_owned_listing,
    update_owned_listing,
)
from skrudj.listing_validation import (
    parse_price,
    photo_metadata_from_message,
    validate_image_metadata,
    validate_image_signature,
    validate_photo_count,
    validate_text_field,
)
from skrudj.notifications import notify_telegram_admins

logger = logging.getLogger(__name__)

router = Router()

WELCOME_TEXT = (
    "🦆 Добро пожаловать в «Скрудж Макдак» — барахолку WhiteBelStudio!\n\n"
    "Здесь можно искать товары и размещать собственные объявления. "
    "Объявления проходят модерацию перед публикацией.\n\n"
    "📌 Основные правила:\n"
    "• Указывайте точные цену, описание и город.\n"
    "• Размещайте только реальные и разрешённые к продаже товары.\n"
    "• Не публикуйте чужие персональные данные и обманчивую информацию.\n"
    "• Уважайте других пользователей; при проблеме обратитесь в поддержку.\n\n"
    "Выберите действие в меню ниже. Полные правила доступны по кнопке «📜 Правила»."
)

RULES_TEXT = (
    "📜 Правила барахолки «Скрудж Макдак»\n\n"
    "1. Публикуйте только достоверные объявления о товарах, которые вы вправе продавать.\n"
    "2. Указывайте корректные название, категорию, описание, цену и город.\n"
    "3. Не размещайте запрещённые товары, мошеннические предложения, спам или дубли объявлений.\n"
    "4. Не публикуйте пароли, платёжные данные, домашние адреса и другие чужие личные данные.\n"
    "5. Используйте только фотографии, которые разрешено публиковать.\n"
    "6. Объявления проходят модерацию; модератор может отклонить публикацию, нарушающую правила.\n"
    "7. Общайтесь уважительно и не пытайтесь обмануть покупателей или продавцов.\n"
    "8. Если заметили нарушение, обратитесь в поддержку.\n\n"
    "Размещая объявление, вы подтверждаете, что информация точна и соответствует правилам."
)

HELP_TEXT = (
    "ℹ️ Помощь по «Скрудж Макдак»\n\n"
    "/start — открыть приветствие и главное меню.\n"
    "/rules — прочитать правила.\n"
    "/help — открыть эту справку.\n"
    "/cancel — отменить текущее действие.\n"
    "Каталог: откройте «🛍️ Каталог» для поиска по названию, категории, описанию или городу. "
    "Отправьте /all внутри каталога, чтобы увидеть все опубликованные объявления."
)

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛍️ Каталог"), KeyboardButton(text="➕ Разместить объявление")],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📦 Мои объявления")],
        [KeyboardButton(text="❤️ Избранное"), KeyboardButton(text="🆘 Поддержка")],
        [KeyboardButton(text="📜 Правила"), KeyboardButton(text="ℹ️ Помощь")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие",
)


class CatalogForm(StatesGroup):
    """State for searching the published marketplace catalog."""

    query = State()


class ReportForm(StatesGroup):
    """Collect a concise reason for a listing report."""

    reason = State()


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


def _profile_text(user, seller_stats: dict[str, int]) -> str:
    """Format a seller profile without requesting sensitive contact details."""
    display_name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    username = f"@{user.username}" if user.username else "не указан"
    return (
        "👤 Профиль продавца\n\n"
        f"Имя: {display_name or 'не указано'}\n"
        f"Telegram: {username}\n"
        f"ID пользователя: {user.telegram_id}\n\n"
        "📦 Статистика объявлений\n"
        f"Всего: {seller_stats['total']}\n"
        f"На модерации: {seller_stats['pending']}\n"
        f"Опубликовано: {seller_stats['published']}\n"
        f"Отклонено: {seller_stats['rejected']}\n\n"
        "Профиль создаётся автоматически по данным Telegram. "
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

        await message.answer(WELCOME_TEXT, reply_markup=MAIN_MENU)

    @router.message(Command("rules"))
    @router.message(F.text == "📜 Правила")
    async def rules_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer(RULES_TEXT, reply_markup=MAIN_MENU)

    @router.message(Command("help"))
    @router.message(F.text == "ℹ️ Помощь")
    async def help_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer(HELP_TEXT, reply_markup=MAIN_MENU)

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

        async with session_factory() as session:
            seller_stats = await get_seller_statistics(session, message.from_user.id)

        await message.answer(_profile_text(user, seller_stats), reply_markup=MAIN_MENU)

    @router.message(Command("cancel"))
    async def cancel_listing_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Текущее действие отменено.", reply_markup=MAIN_MENU)

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
            photo = photo_metadata_from_message(message)
            if any(item["file_unique_id"] == photo["file_unique_id"] for item in photos):
                await message.answer("Это фото уже добавлено. Отправьте другое или /done.")
                return
            validate_photo_count(len(photos), settings.max_photos_per_listing)

            # Verify the actual downloaded bytes, not only Telegram's MIME metadata.
            downloaded = await message.bot.download(photo["file_id"])
            if downloaded is None:
                raise ValueError("Не удалось получить файл. Отправьте изображение ещё раз.")
            image_bytes = downloaded.read()
            validate_image_metadata(
                mime_type=photo["mime_type"],
                size_bytes=len(image_bytes),
                max_size_bytes=settings.max_upload_size_mb * 1024 * 1024,
            )
            validate_image_signature(image_bytes, photo["mime_type"])
        except ValueError as exc:
            await message.answer(str(exc))
            return
        except Exception:
            logger.exception("Failed to download or validate listing image.")
            await message.answer(
                "Не удалось проверить изображение из-за временной ошибки. "
                "Попробуйте отправить его ещё раз."
            )
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
        status_labels = {
            "pending": "⏳ На модерации",
            "published": "🟢 Опубликовано",
            "rejected": "🔴 Отклонено",
            "unpublished": "⏸ Снято с публикации",
            "sold": "🎉 Продано",
        }
        for listing in listings:
            action_row = [
                InlineKeyboardButton(
                    text="✏️ Изменить",
                    callback_data=f"listing_edit:{listing.id}",
                ),
            ]
            if listing.status == "published":
                action_row.append(
                    InlineKeyboardButton(
                        text="⏸ Снять с публикации",
                        callback_data=f"listing_unpublish:{listing.id}",
                    )
                )
            action_row.append(
                InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"listing_delete:{listing.id}",
                )
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[action_row])
            await message.answer(
                f"#{listing.id} · {listing.title}\n"
                f"Цена: {listing.price:.2f} ₽ · {listing.city}\n"
                f"Статус: {status_labels.get(listing.status, listing.status)}",
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

    @router.callback_query(F.data.startswith("listing_unpublish:"))
    async def listing_unpublish_handler(callback: CallbackQuery) -> None:
        if callback.from_user is None or callback.message is None:
            await callback.answer("Не удалось снять объявление с публикации.", show_alert=True)
            return
        try:
            listing_id = int(callback.data.split(":", 1)[1])
        except (ValueError, AttributeError):
            await callback.answer("Некорректный номер объявления.", show_alert=True)
            return
        async with session_factory() as session:
            listing = await unpublish_owned_listing(
                session,
                listing_id=listing_id,
                seller_telegram_id=callback.from_user.id,
            )
        if listing is None:
            await callback.answer(
                "Объявление не найдено, не принадлежит вам или уже не опубликовано.",
                show_alert=True,
            )
            return
        await callback.message.answer(
            f"⏸ Объявление #{listing.id} снято с публикации. "
            "Оно останется в разделе «Мои объявления».",
            reply_markup=MAIN_MENU,
        )
        await callback.answer("Публикация остановлена.")

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


    async def send_catalog_results(
        message: Message, state: FSMContext, query: str, offset: int = 0
    ) -> None:
        page_size = 5
        async with session_factory() as session:
            listings = await search_published_listings(
                session, query=query, limit=page_size + 1, offset=offset
            )
            listing_photos = {
                listing.id: await get_listing_photos(session, listing.id, limit=1)
                for listing in listings[:page_size]
            }

        has_more = len(listings) > page_size
        page = listings[:page_size]
        if not page and offset == 0:
            message_text = (
                "🔎 По вашему запросу ничего не найдено."
                if query
                else "🛍️ Пока нет опубликованных объявлений."
            )
            await message.answer(message_text, reply_markup=MAIN_MENU)
            return
        if not page:
            await message.answer("Больше объявлений нет.", reply_markup=MAIN_MENU)
            return

        heading = (
            f"🔎 Результаты поиска: «{query[:100]}»"
            if query
            else "🛍️ Каталог опубликованных объявлений"
        )
        await message.answer(
            f"{heading}\nПоказаны объявления {offset + 1}–{offset + len(page)}."
        )
        for listing in page:
            description = listing.description.strip()
            if len(description) > 400:
                description = description[:397].rstrip() + "..."
            caption = (
                f"🛍️ {listing.title}\n"
                f"Категория: {listing.category}\n"
                f"Цена: {listing.price:.2f} ₽\n"
                f"Город: {listing.city}\n\n"
                f"{description}\n\n"
                f"Объявление #{listing.id}"
            )
            photos = listing_photos.get(listing.id, [])
            action_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="❤️ В избранное", callback_data=f"favorite_toggle:{listing.id}"),
                    InlineKeyboardButton(text="🚩 Пожаловаться", callback_data=f"report_start:{listing.id}"),
                ]
            ])
            if photos:
                await message.answer_photo(photos[0].file_id, caption=caption, reply_markup=action_keyboard)
            else:
                await message.answer(caption, reply_markup=action_keyboard)

        if has_more:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="➡️ Следующие объявления",
                            callback_data=f"catalog_next:{offset + page_size}",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="🔎 Новый поиск", callback_data="catalog_new_search"
                        )
                    ],
                ]
            )
            await message.answer("Продолжить просмотр?", reply_markup=keyboard)
        else:
            await message.answer(
                "Это все объявления по запросу.",
                reply_markup=MAIN_MENU,
            )

    @router.message(F.text == "🛍️ Каталог")
    async def catalog_start_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await state.set_state(CatalogForm.query)
        await message.answer(
            "🛍️ Каталог объявлений\n\n"
            "Введите ключевое слово, категорию или город. "
            "Поиск выполняется по названию, категории, описанию и городу.\n"
            "Чтобы показать все опубликованные объявления, отправьте /all. "
            "Для отмены — /cancel."
        )

    @router.message(CatalogForm.query, Command("all"))
    async def catalog_all_handler(message: Message, state: FSMContext) -> None:
        await state.update_data(catalog_query="")
        await send_catalog_results(message, state, query="", offset=0)

    @router.message(CatalogForm.query, Command("cancel"))
    async def catalog_cancel_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Поиск отменён.", reply_markup=MAIN_MENU)

    @router.message(CatalogForm.query)
    async def catalog_search_handler(message: Message, state: FSMContext) -> None:
        query = (message.text or "").strip()
        if not query:
            await message.answer("Введите текст для поиска или отправьте /all.")
            return
        if len(query) > 100:
            await message.answer("Поисковый запрос должен быть не длиннее 100 символов.")
            return
        await state.update_data(catalog_query=query)
        await send_catalog_results(message, state, query=query, offset=0)

    @router.callback_query(F.data.startswith("catalog_next:"))
    async def catalog_next_handler(callback: CallbackQuery, state: FSMContext) -> None:
        if callback.message is None:
            await callback.answer()
            return
        try:
            offset = int(callback.data.split(":", 1)[1])
            if offset < 0 or offset > 100000:
                raise ValueError
        except (ValueError, AttributeError):
            await callback.answer("Некорректная страница каталога.", show_alert=True)
            return
        data = await state.get_data()
        query = str(data.get("catalog_query", ""))
        await send_catalog_results(callback.message, state, query=query, offset=offset)
        await callback.answer()

    @router.callback_query(F.data == "catalog_new_search")
    async def catalog_new_search_handler(
        callback: CallbackQuery, state: FSMContext
    ) -> None:
        if callback.message is not None:
            await state.clear()
            await state.set_state(CatalogForm.query)
            await callback.message.answer(
                "Введите новое ключевое слово, категорию или город.\n"
                "Для просмотра всего каталога отправьте /all."
            )
        await callback.answer()



    @router.callback_query(F.data.startswith("favorite_toggle:"))
    async def favorite_toggle_handler(callback: CallbackQuery) -> None:
        if callback.from_user is None:
            await callback.answer("Не удалось определить пользователя.", show_alert=True)
            return
        try:
            listing_id = int(callback.data.split(":", 1)[1])
            if listing_id <= 0:
                raise ValueError
        except (ValueError, AttributeError):
            await callback.answer("Некорректный номер объявления.", show_alert=True)
            return
        async with session_factory() as session:
            try:
                added = await toggle_favorite(
                    session, user_telegram_id=callback.from_user.id, listing_id=listing_id
                )
            except Exception:
                logger.exception("Could not toggle favorite for listing %s", listing_id)
                await callback.answer("Не удалось обновить избранное.", show_alert=True)
                return
        if added is None:
            await callback.answer("Объявление больше недоступно.", show_alert=True)
        elif added:
            await callback.answer("Добавлено в избранное ❤️")
        else:
            await callback.answer("Удалено из избранного.")

    @router.message(F.text == "❤️ Избранное")
    async def favorites_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        if message.from_user is None:
            return
        async with session_factory() as session:
            listings = await get_user_favorite_listings(session, message.from_user.id)
            photos_by_listing = {
                listing.id: await get_listing_photos(session, listing.id, limit=1)
                for listing in listings
            }
        if not listings:
            await message.answer("❤️ Избранное пока пусто.", reply_markup=MAIN_MENU)
            return
        await message.answer(f"❤️ Ваше избранное: {len(listings)} объявл.")
        for listing in listings:
            caption = (
                f"🛍️ {listing.title}\nКатегория: {listing.category}\n"
                f"Цена: {listing.price:.2f} ₽\nГород: {listing.city}\n"
                f"Объявление #{listing.id}"
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💔 Убрать", callback_data=f"favorite_toggle:{listing.id}"),
                InlineKeyboardButton(text="🚩 Пожаловаться", callback_data=f"report_start:{listing.id}"),
            ]])
            photos = photos_by_listing.get(listing.id, [])
            if photos:
                await message.answer_photo(photos[0].file_id, caption=caption, reply_markup=keyboard)
            else:
                await message.answer(caption, reply_markup=keyboard)

    @router.callback_query(F.data.startswith("report_start:"))
    async def report_start_handler(callback: CallbackQuery, state: FSMContext) -> None:
        if callback.from_user is None or callback.message is None:
            await callback.answer("Не удалось начать жалобу.", show_alert=True)
            return
        try:
            listing_id = int(callback.data.split(":", 1)[1])
            if listing_id <= 0:
                raise ValueError
        except (ValueError, AttributeError):
            await callback.answer("Некорректный номер объявления.", show_alert=True)
            return
        async with session_factory() as session:
            from skrudj.database import get_listing
            listing = await get_listing(session, listing_id)
            if listing is None or listing.status != "published":
                await callback.answer("Объявление уже недоступно.", show_alert=True)
                return
            if listing.seller_telegram_id == callback.from_user.id:
                await callback.answer("Нельзя пожаловаться на собственное объявление.", show_alert=True)
                return
        await state.clear()
        await state.update_data(report_listing_id=listing_id)
        await state.set_state(ReportForm.reason)
        await callback.message.answer(
            f"🚩 Напишите причину жалобы на объявление #{listing_id} (до 500 символов). "
            "Для отмены отправьте /cancel."
        )
        await callback.answer()

    @router.message(ReportForm.reason, Command("cancel"))
    async def report_cancel_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Жалоба отменена.", reply_markup=MAIN_MENU)

    @router.message(ReportForm.reason)
    async def report_reason_handler(message: Message, state: FSMContext) -> None:
        reason = (message.text or "").strip()
        if not reason or len(reason) > 500:
            await message.answer("Причина должна содержать от 1 до 500 символов. Для отмены — /cancel.")
            return
        data = await state.get_data()
        listing_id = data.get("report_listing_id")
        if not isinstance(listing_id, int):
            await state.clear()
            await message.answer("Сессия жалобы истекла. Начните заново из каталога.")
            return
        async with session_factory() as session:
            try:
                report = await create_listing_report(
                    session, reporter_telegram_id=message.from_user.id,
                    listing_id=listing_id, reason=reason
                )
            except ValueError as exc:
                await state.clear()
                await message.answer(str(exc), reply_markup=MAIN_MENU)
                return
        await state.clear()
        await message.answer(
            f"✅ Жалоба #{report.id} принята и передана на проверку.",
            reply_markup=MAIN_MENU,
        )

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
    setup_admin_handlers(dispatcher, session_factory, get_settings())
    setup_telegram_handlers(dispatcher, session_factory)
    try:
        logger.info("Starting Telegram bot polling.")
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()
