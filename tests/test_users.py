"""Tests for Telegram profile registration and updates."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from skrudj.database import (
    Base,
    create_listing,
    get_seller_statistics,
    get_telegram_user,
    make_session_factory,
    register_or_update_telegram_user,
)


@pytest.mark.asyncio
async def test_registers_and_updates_telegram_profile() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = make_session_factory(engine)
        async with session_factory() as session:
            created = await register_or_update_telegram_user(
                session,
                telegram_id=123456,
                username="first_name",
                first_name="Alex",
                last_name=None,
            )
            assert created.telegram_id == 123456
            assert created.username == "first_name"
            assert created.first_name == "Alex"

            updated = await register_or_update_telegram_user(
                session,
                telegram_id=123456,
                username="new_name",
                first_name="Alexandra",
                last_name="Smith",
            )
            assert updated.username == "new_name"
            assert updated.first_name == "Alexandra"
            assert updated.last_name == "Smith"

            saved = await get_telegram_user(session, 123456)
            assert saved is not None
            assert saved.telegram_id == 123456
            assert saved.first_name == "Alexandra"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_seller_statistics_are_scoped_to_the_seller() -> None:
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

            await create_listing(
                session,
                seller_telegram_id=111,
                title="Pending item",
                category="Books",
                description="A pending listing description.",
                price=Decimal("100.00"),
                city="Belorechensk",
            )
            published = await create_listing(
                session,
                seller_telegram_id=111,
                title="Published item",
                category="Books",
                description="A published listing description.",
                price=Decimal("200.00"),
                city="Belorechensk",
            )
            published.status = "published"
            await session.commit()
            rejected = await create_listing(
                session,
                seller_telegram_id=111,
                title="Rejected item",
                category="Books",
                description="A rejected listing description.",
                price=Decimal("300.00"),
                city="Belorechensk",
            )
            rejected.status = "rejected"
            await session.commit()

            assert await get_seller_statistics(session, 111) == {
                "total": 3,
                "pending": 1,
                "published": 1,
                "rejected": 1,
            }
            assert await get_seller_statistics(session, 222) == {
                "total": 0,
                "pending": 0,
                "published": 0,
                "rejected": 0,
            }
    finally:
        await engine.dispose()
