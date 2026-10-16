"""Database engine, user model, and profile persistence helpers."""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, String, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from skrudj.config import get_settings


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


class TelegramUser(Base):
    """Minimal Telegram marketplace profile; no phone or address is collected."""

    __tablename__ = "telegram_users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(256), default="")
    last_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


def make_engine(database_url: str | None = None):
    """Create an async SQLAlchemy engine for the configured database."""
    url = database_url or get_settings().database_url
    return create_async_engine(url, pool_pre_ping=True)


def make_session_factory(engine):
    """Create a reusable async session factory."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def initialize_database(engine) -> None:
    """Create tables for the initial scaffold."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def register_or_update_telegram_user(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None,
    first_name: str,
    last_name: str | None,
) -> TelegramUser:
    """Create a Telegram profile or refresh its public Telegram fields."""
    user = await session.get(TelegramUser, telegram_id)
    if user is None:
        user = TelegramUser(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        session.add(user)
    else:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        user.updated_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(user)
    return user


async def get_telegram_user(session: AsyncSession, telegram_id: int) -> TelegramUser | None:
    """Return a profile by Telegram ID."""
    result = await session.execute(
        select(TelegramUser).where(TelegramUser.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()
