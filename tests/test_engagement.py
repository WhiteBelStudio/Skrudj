"""Tests for favorites and listing reports."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from skrudj.database import (
    Base,
    Favorite,
    create_listing,
    create_listing_report,
    get_pending_listing_reports,
    get_user_favorite_listings,
    make_session_factory,
    register_or_update_telegram_user,
    resolve_listing_report,
    toggle_favorite,
)


@pytest.mark.asyncio
async def test_favorites_toggle_without_duplicates_and_only_published() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = make_session_factory(engine)
        async with factory() as session:
            for user_id in (101, 202):
                await register_or_update_telegram_user(
                    session, telegram_id=user_id, username=None,
                    first_name="User", last_name=None
                )
            listing = await create_listing(
                session, seller_telegram_id=101, title="Item", category="Books",
                description="A listing description long enough.", price=Decimal("10"),
                city="Belorechensk"
            )
            assert await toggle_favorite(
                session, user_telegram_id=202, listing_id=listing.id
            ) is None
            listing.status = "published"
            await session.commit()
            assert await toggle_favorite(
                session, user_telegram_id=202, listing_id=listing.id
            ) is True
            assert await toggle_favorite(
                session, user_telegram_id=202, listing_id=listing.id
            ) is False
            assert await toggle_favorite(
                session, user_telegram_id=202, listing_id=listing.id
            ) is True
            favorites = await get_user_favorite_listings(session, 202)
            assert [item.id for item in favorites] == [listing.id]
            count = await session.scalar(select(Favorite).where(Favorite.user_telegram_id == 202))
            assert count is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reports_reject_own_unpublished_and_duplicate_and_can_be_resolved() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = make_session_factory(engine)
        async with factory() as session:
            for user_id in (101, 202):
                await register_or_update_telegram_user(
                    session, telegram_id=user_id, username=None,
                    first_name="User", last_name=None
                )
            listing = await create_listing(
                session, seller_telegram_id=101, title="Item", category="Books",
                description="A listing description long enough.", price=Decimal("10"),
                city="Belorechensk"
            )
            with pytest.raises(ValueError, match="не опубликовано"):
                await create_listing_report(
                    session, reporter_telegram_id=202, listing_id=listing.id, reason="Spam"
                )
            listing.status = "published"
            await session.commit()
            with pytest.raises(ValueError, match="собственное"):
                await create_listing_report(
                    session, reporter_telegram_id=101, listing_id=listing.id, reason="Spam"
                )
            report = await create_listing_report(
                session, reporter_telegram_id=202, listing_id=listing.id, reason="  Spam  "
            )
            assert report.reason == "Spam"
            assert report.status == "pending"
            with pytest.raises(ValueError, match="уже отправляли"):
                await create_listing_report(
                    session, reporter_telegram_id=202, listing_id=listing.id, reason="Duplicate"
                )
            assert [item.id for item in await get_pending_listing_reports(session)] == [report.id]
            resolved = await resolve_listing_report(session, report_id=report.id)
            assert resolved is not None and resolved.status == "reviewed"
            assert await get_pending_listing_reports(session) == []
            assert await resolve_listing_report(session, report_id=report.id) is None
            with pytest.raises(ValueError, match="500"):
                await create_listing_report(
                    session, reporter_telegram_id=202, listing_id=listing.id, reason="x" * 501
                )
    finally:
        await engine.dispose()
