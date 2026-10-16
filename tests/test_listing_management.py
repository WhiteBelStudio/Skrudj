"""Tests for seller-scoped listing management."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from skrudj.database import (
    Base,
    create_listing,
    delete_owned_listing,
    get_user_listings,
    make_session_factory,
    register_or_update_telegram_user,
    update_owned_listing,
)


@pytest.mark.asyncio
async def test_seller_can_list_edit_and_delete_only_their_own_listing() -> None:
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
                title="Old title",
                category="Books",
                description="A used book in good condition.",
                price=Decimal("100.00"),
                city="Belorechensk",
            )

            seller_listings = await get_user_listings(session, 111)
            assert [item.id for item in seller_listings] == [listing.id]
            assert await get_user_listings(session, 222) == []

            denied_update = await update_owned_listing(
                session,
                listing_id=listing.id,
                seller_telegram_id=222,
                field="title",
                value="Hijacked title",
            )
            assert denied_update is None

            updated = await update_owned_listing(
                session,
                listing_id=listing.id,
                seller_telegram_id=111,
                field="title",
                value="New title",
            )
            assert updated is not None
            assert updated.title == "New title"
            assert updated.status == "pending"

            denied_delete = await delete_owned_listing(
                session, listing_id=listing.id, seller_telegram_id=222
            )
            assert denied_delete is False
            assert await get_user_listings(session, 111)

            deleted = await delete_owned_listing(
                session, listing_id=listing.id, seller_telegram_id=111
            )
            assert deleted is True
            assert await get_user_listings(session, 111) == []
    finally:
        await engine.dispose()
