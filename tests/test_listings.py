"""Tests for marketplace listing persistence."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from skrudj.database import (
    Base,
    ListingPhoto,
    create_listing,
    get_listing,
    make_session_factory,
    register_or_update_telegram_user,
    unpublish_owned_listing,
    get_user_listings,
    update_owned_listing,
)


@pytest.mark.asyncio
async def test_creates_listing_pending_moderation() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = make_session_factory(engine)
        async with session_factory() as session:
            await register_or_update_telegram_user(
                session,
                telegram_id=987654,
                username="seller",
                first_name="Seller",
                last_name=None,
            )
            listing = await create_listing(
                session,
                seller_telegram_id=987654,
                title="Wireless headphones",
                category="Electronics",
                description="Wireless headphones in good condition.",
                price=Decimal("1500.50"),
                city="Белореченск",
            )

            assert listing.id is not None
            assert listing.status == "pending"
            assert listing.price == Decimal("1500.50")

            saved = await get_listing(session, listing.id)
            assert saved is not None
            assert saved.title == "Wireless headphones"
            assert saved.category == "Electronics"
            assert saved.description == "Wireless headphones in good condition."
            assert saved.price == Decimal("1500.50")
            assert saved.seller_telegram_id == 987654
            assert saved.city == "Белореченск"

            photo_listing = await create_listing(
                session,
                seller_telegram_id=987654,
                title="Camera",
                category="Electronics",
                description="Camera in excellent working condition.",
                price=Decimal("5000.00"),
                city="Белореченск",
                photos=[
                    {
                        "file_id": "telegram-file-id",
                        "file_unique_id": "telegram-unique-id",
                        "mime_type": "image/jpeg",
                        "size_bytes": 2048,
                    }
                ],
            )
            photos = (
                await session.execute(
                    select(ListingPhoto).where(
                        ListingPhoto.listing_id == photo_listing.id
                    )
                )
            ).scalars().all()
            assert len(photos) == 1
            assert photos[0].file_id == "telegram-file-id"
            assert photos[0].mime_type == "image/jpeg"
            assert photos[0].position == 1
    finally:
        await engine.dispose()



@pytest.mark.asyncio
async def test_seller_can_unpublish_only_their_published_listing() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = make_session_factory(engine)
        async with session_factory() as session:
            for telegram_id, name in ((111, "Seller A"), (222, "Seller B")):
                await register_or_update_telegram_user(
                    session,
                    telegram_id=telegram_id,
                    username=None,
                    first_name=name,
                    last_name=None,
                )

            listing = await create_listing(
                session,
                seller_telegram_id=111,
                title="Published item",
                category="Books",
                description="A published listing description.",
                price=Decimal("100.00"),
                city="Belorechensk",
            )
            listing.status = "published"
            await session.commit()

            assert await unpublish_owned_listing(
                session, listing_id=listing.id, seller_telegram_id=222
            ) is None
            assert listing.status == "published"

            unpublished = await unpublish_owned_listing(
                session, listing_id=listing.id, seller_telegram_id=111
            )
            assert unpublished is not None
            assert unpublished.status == "unpublished"

            assert await unpublish_owned_listing(
                session, listing_id=listing.id, seller_telegram_id=111
            ) is None
            seller_listings = await get_user_listings(session, 111)
            assert len(seller_listings) == 1
            assert seller_listings[0].status == "unpublished"

            updated = await update_owned_listing(
                session,
                listing_id=listing.id,
                seller_telegram_id=111,
                field="title",
                value="Updated title",
            )
            assert updated is not None
            assert updated.title == "Updated title"
            assert updated.status == "pending"
    finally:
        await engine.dispose()
