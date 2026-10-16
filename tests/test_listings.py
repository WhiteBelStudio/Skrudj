"""Tests for marketplace listing persistence."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from skrudj.database import (
    Base,
    create_listing,
    get_listing,
    make_session_factory,
    register_or_update_telegram_user,
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
            assert saved.seller_telegram_id == 987654
            assert saved.city == "Белореченск"
    finally:
        await engine.dispose()
