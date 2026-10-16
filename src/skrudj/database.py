"""Database engine, user and listing models, and persistence helpers."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, Text, select
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


class Listing(Base):
    """A marketplace listing submitted by a Telegram user."""

    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    seller_telegram_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_users.telegram_id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
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


async def create_listing(
    session: AsyncSession,
    *,
    seller_telegram_id: int,
    title: str,
    category: str,
    description: str,
    price: Decimal,
    city: str,
) -> Listing:
    """Persist a validated listing and leave it pending moderation."""
    listing = Listing(
        seller_telegram_id=seller_telegram_id,
        title=title,
        category=category,
        description=description,
        price=price,
        city=city,
        status="pending",
    )
    session.add(listing)
    await session.commit()
    await session.refresh(listing)
    return listing


async def get_listing(session: AsyncSession, listing_id: int) -> Listing | None:
    """Return one listing by its database ID."""
    return await session.get(Listing, listing_id)



async def get_user_listings(
    session: AsyncSession, seller_telegram_id: int, *, limit: int = 20
) -> list[Listing]:
    """Return a seller's newest listings, never exposing another seller's records."""
    result = await session.execute(
        select(Listing)
        .where(Listing.seller_telegram_id == seller_telegram_id)
        .order_by(Listing.created_at.desc(), Listing.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def update_owned_listing(
    session: AsyncSession,
    *,
    listing_id: int,
    seller_telegram_id: int,
    field: str,
    value: str | Decimal,
) -> Listing | None:
    """Update an allowed field only when the listing belongs to the requesting seller."""
    allowed_fields = {"title", "category", "description", "price", "city"}
    if field not in allowed_fields:
        raise ValueError("Unsupported listing field")

    result = await session.execute(
        select(Listing).where(
            Listing.id == listing_id,
            Listing.seller_telegram_id == seller_telegram_id,
        )
    )
    listing = result.scalar_one_or_none()
    if listing is None:
        return None

    setattr(listing, field, value)
    listing.status = "pending"
    await session.commit()
    await session.refresh(listing)
    return listing


async def delete_owned_listing(
    session: AsyncSession, *, listing_id: int, seller_telegram_id: int
) -> bool:
    """Delete a listing only when it belongs to the requesting seller."""
    result = await session.execute(
        select(Listing).where(
            Listing.id == listing_id,
            Listing.seller_telegram_id == seller_telegram_id,
        )
    )
    listing = result.scalar_one_or_none()
    if listing is None:
        return False

    await session.delete(listing)
    await session.commit()
    return True
