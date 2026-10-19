"""Tests for support ticket lifecycle and message permissions."""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from skrudj.database import (
    Base,
    add_support_message,
    close_support_ticket,
    create_support_ticket,
    get_open_support_tickets,
    get_support_messages,
    get_support_ticket,
    get_user_support_tickets,
    make_session_factory,
    register_or_update_telegram_user,
)


@pytest.mark.asyncio
async def test_support_ticket_persists_initial_message_and_photo() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = make_session_factory(engine)
        async with factory() as session:
            await register_or_update_telegram_user(
                session, telegram_id=101, username=None, first_name="Buyer", last_name=None
            )
            ticket = await create_support_ticket(
                session, user_telegram_id=101, body="Не открывается каталог",
                attachment_file_id="telegram-photo-id", attachment_type="photo"
            )
            history = await get_support_messages(session, ticket.id)
            assert ticket.status == "open"
            assert len(history) == 1
            assert history[0].body == "Не открывается каталог"
            assert history[0].attachment_file_id == "telegram-photo-id"
            assert [item.id for item in await get_user_support_tickets(session, 101)] == [ticket.id]
            assert [item.id for item in await get_open_support_tickets(session)] == [ticket.id]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_support_reply_reopens_ticket_and_close_preserves_history() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = make_session_factory(engine)
        async with factory() as session:
            await register_or_update_telegram_user(
                session, telegram_id=101, username=None, first_name="Buyer", last_name=None
            )
            ticket = await create_support_ticket(
                session, user_telegram_id=101, body="Нужна помощь"
            )
            reply = await add_support_message(
                session, ticket_id=ticket.id, sender_telegram_id=900,
                sender_role="staff", body="Проверяем проблему"
            )
            assert reply.sender_role == "staff"
            assert (await get_support_ticket(session, ticket.id)).status == "answered"
            await add_support_message(
                session, ticket_id=ticket.id, sender_telegram_id=101,
                sender_role="user", body="Добавляю детали"
            )
            assert (await get_support_ticket(session, ticket.id)).status == "open"
            closed = await close_support_ticket(session, ticket_id=ticket.id)
            assert closed is not None and closed.status == "closed"
            assert await close_support_ticket(session, ticket_id=ticket.id) is None
            assert len(await get_support_messages(session, ticket.id)) == 3
            with pytest.raises(ValueError, match="закрыто"):
                await add_support_message(
                    session, ticket_id=ticket.id, sender_telegram_id=101,
                    sender_role="user", body="Новое сообщение"
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_support_rejects_invalid_message_lengths_and_attachment_types() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = make_session_factory(engine)
        async with factory() as session:
            await register_or_update_telegram_user(
                session, telegram_id=101, username=None, first_name="Buyer", last_name=None
            )
            with pytest.raises(ValueError, match="2000"):
                await create_support_ticket(
                    session, user_telegram_id=101, body="x" * 2001
                )
            with pytest.raises(ValueError, match="фотографии"):
                await create_support_ticket(
                    session, user_telegram_id=101, body="Помогите",
                    attachment_file_id="bad", attachment_type="document"
                )
    finally:
        await engine.dispose()
