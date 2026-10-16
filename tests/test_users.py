"""Tests for Telegram profile registration and updates."""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from skrudj.database import (
    Base,
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
