"""Tests for role management, blocking and aggregate admin statistics."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from skrudj.database import (
    Base,
    create_listing,
    get_admin_statistics,
    get_user_access,
    make_session_factory,
    register_or_update_telegram_user,
    set_user_block,
    set_user_role,
)


@pytest.mark.asyncio
async def test_roles_blocks_and_statistics_are_persisted() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = make_session_factory(engine)
        async with session_factory() as session:
            await register_or_update_telegram_user(
                session,
                telegram_id=123,
                username="seller",
                first_name="Seller",
                last_name=None,
            )
            listing = await create_listing(
                session,
                seller_telegram_id=123,
                title="Desk lamp",
                category="Home",
                description="Desk lamp in good working condition.",
                price=Decimal("25.00"),
                city="Belorechensk",
            )

            role = await set_user_role(
                session, telegram_id=123, role="moderator"
            )
            assert role.role == "moderator"
            assert (await get_user_access(session, 123)).role == "moderator"

            blocked = await set_user_block(
                session,
                telegram_id=123,
                blocked=True,
                reason="Repeated spam",
            )
            assert blocked.is_blocked is True
            assert blocked.block_reason == "Repeated spam"

            unblocked = await set_user_block(
                session, telegram_id=123, blocked=False
            )
            assert unblocked.is_blocked is False
            assert unblocked.block_reason is None

            stats = await get_admin_statistics(session)
            assert stats == {
                "users": 1,
                "listings": 1,
                "pending_listings": 1,
                "published_listings": 0,
                "blocked_users": 0,
                "staff": 1,
            }
            assert listing.status == "pending"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_invalid_role_is_rejected() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = make_session_factory(engine)
        async with session_factory() as session:
            with pytest.raises(ValueError, match="Unsupported role"):
                await set_user_role(session, telegram_id=123, role="owner")
    finally:
        await engine.dispose()
