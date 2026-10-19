"""Tests for persistent marketplace news notification preferences."""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from skrudj.database import (
    Base,
    get_news_notifications_enabled,
    get_news_subscriber_ids,
    make_session_factory,
    register_or_update_telegram_user,
    set_news_notifications_enabled,
)


@pytest.mark.asyncio
async def test_news_notifications_default_to_enabled_and_can_be_disabled() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            await register_or_update_telegram_user(
                session,
                telegram_id=101,
                username=None,
                first_name="Seller",
                last_name=None,
            )
            assert await get_news_notifications_enabled(session, 101) is True

            await set_news_notifications_enabled(session, telegram_id=101, enabled=False)
            assert await get_news_notifications_enabled(session, 101) is False

            await set_news_notifications_enabled(session, telegram_id=101, enabled=True)
            assert await get_news_notifications_enabled(session, 101) is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_news_subscriber_list_excludes_only_users_who_opted_out() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            for telegram_id in (101, 202, 303):
                await register_or_update_telegram_user(
                    session,
                    telegram_id=telegram_id,
                    username=None,
                    first_name="User",
                    last_name=None,
                )
            await set_news_notifications_enabled(session, telegram_id=202, enabled=False)

            assert await get_news_subscriber_ids(session) == [101, 303]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cannot_save_notification_preference_for_unknown_user() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = make_session_factory(engine)

        async with session_factory() as session:
            with pytest.raises(ValueError, match="командой /start"):
                await set_news_notifications_enabled(
                    session, telegram_id=404, enabled=False
                )
    finally:
        await engine.dispose()
