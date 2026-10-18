"""Tests for published catalog search."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from skrudj.database import (
    Base,
    create_listing,
    make_session_factory,
    register_or_update_telegram_user,
    search_published_listings,
)


@pytest.mark.asyncio
async def test_search_only_returns_matching_published_listings() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = make_session_factory(engine)
        async with factory() as session:
            await register_or_update_telegram_user(
                session, telegram_id=7001, username=None, first_name="Seller", last_name=None
            )
            published = await create_listing(
                session, seller_telegram_id=7001, title="Camera", category="Electronics",
                description="Compact camera in good condition.", price=Decimal("4500.00"),
                city="Краснодар",
            )
            published.status = "published"
            pending = await create_listing(
                session, seller_telegram_id=7001, title="Camera case", category="Accessories",
                description="Protective case waiting for review.", price=Decimal("300.00"),
                city="Краснодар",
            )
            await session.commit()

            found = await search_published_listings(session, query="camera")
            assert [item.id for item in found] == [published.id]
            found_by_city = await search_published_listings(session, query="Краснодар")
            assert [item.id for item in found_by_city] == [published.id]
            all_public = await search_published_listings(session)
            assert [item.id for item in all_public] == [published.id]
            assert pending.id not in [item.id for item in all_public]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_search_pagination_and_invalid_parameters() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = make_session_factory(engine)
        async with factory() as session:
            await register_or_update_telegram_user(
                session, telegram_id=7002, username=None, first_name="Seller", last_name=None
            )
            ids = []
            for index in range(3):
                listing = await create_listing(
                    session, seller_telegram_id=7002, title=f"Item {index}", category="Misc",
                    description="A searchable item description.", price=Decimal("10.00"),
                    city="Белореченск",
                )
                listing.status = "published"
                ids.append(listing.id)
            await session.commit()

            first = await search_published_listings(session, limit=2, offset=0)
            second = await search_published_listings(session, limit=2, offset=2)
            assert [item.id for item in first] == list(reversed(ids))[:2]
            assert [item.id for item in second] == [ids[0]]
            with pytest.raises(ValueError, match="limit"):
                await search_published_listings(session, limit=0)
            with pytest.raises(ValueError, match="offset"):
                await search_published_listings(session, offset=-1)
    finally:
        await engine.dispose()
