"""Database engine, user and listing models, and persistence helpers."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, Text, func, select
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


class UserAccess(Base):
    """Administrative role and block status for a Telegram account."""

    __tablename__ = "user_access"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role: Mapped[str] = mapped_column(String(24), default="user", nullable=False)
    is_blocked: Mapped[bool] = mapped_column(default=False, nullable=False)
    block_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
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




class ListingPhoto(Base):
    """Telegram-hosted image metadata attached to a listing."""

    __tablename__ = "listing_photos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    file_id: Mapped[str] = mapped_column(String(512), nullable=False)
    file_unique_id: Mapped[str] = mapped_column(String(256), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    position: Mapped[int] = mapped_column(nullable=False)


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
    photos: list[dict[str, str | int]] | None = None,
) -> Listing:
    """Persist a listing and its validated photos, leaving it pending moderation."""
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
    await session.flush()
    for position, photo in enumerate(photos or [], start=1):
        session.add(
            ListingPhoto(
                listing_id=listing.id,
                file_id=str(photo["file_id"]),
                file_unique_id=str(photo["file_unique_id"]),
                mime_type=str(photo["mime_type"]),
                size_bytes=int(photo["size_bytes"]),
                position=position,
            )
        )
    await session.commit()
    await session.refresh(listing)
    return listing


async def get_listing(session: AsyncSession, listing_id: int) -> Listing | None:
    """Return one listing by its database ID."""
    return await session.get(Listing, listing_id)


async def search_published_listings(
    session: AsyncSession,
    *,
    query: str = "",
    limit: int = 5,
    offset: int = 0,
) -> list[Listing]:
    """Search only published listings by title, category, description, or city."""
    if not 1 <= limit <= 50:
        raise ValueError("Listing search limit must be between 1 and 50")
    if offset < 0:
        raise ValueError("Listing search offset cannot be negative")

    statement = select(Listing).where(Listing.status == "published")
    normalized_query = query.strip()
    if normalized_query:
        # Treat search input literally: SQL LIKE wildcards must not broaden a
        # user's query into an accidental full-catalog search.
        escaped_query = (
            normalized_query.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped_query}%"
        statement = statement.where(
            Listing.title.ilike(pattern, escape="\\")
            | Listing.category.ilike(pattern, escape="\\")
            | Listing.description.ilike(pattern, escape="\\")
            | Listing.city.ilike(pattern, escape="\\")
        )
    result = await session.execute(
        statement.order_by(Listing.created_at.desc(), Listing.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_listing_photos(
    session: AsyncSession, listing_id: int, *, limit: int = 5
) -> list[ListingPhoto]:
    """Return photos for a listing in their saved display order."""
    result = await session.execute(
        select(ListingPhoto)
        .where(ListingPhoto.listing_id == listing_id)
        .order_by(ListingPhoto.position.asc(), ListingPhoto.id.asc())
        .limit(limit)
    )
    return list(result.scalars().all())



async def get_seller_statistics(
    session: AsyncSession, seller_telegram_id: int
) -> dict[str, int]:
    """Return listing counts for the requested seller only."""
    total = await session.scalar(
        select(func.count())
        .select_from(Listing)
        .where(Listing.seller_telegram_id == seller_telegram_id)
    ) or 0
    pending = await session.scalar(
        select(func.count())
        .select_from(Listing)
        .where(
            Listing.seller_telegram_id == seller_telegram_id,
            Listing.status == "pending",
        )
    ) or 0
    published = await session.scalar(
        select(func.count())
        .select_from(Listing)
        .where(
            Listing.seller_telegram_id == seller_telegram_id,
            Listing.status == "published",
        )
    ) or 0
    rejected = await session.scalar(
        select(func.count())
        .select_from(Listing)
        .where(
            Listing.seller_telegram_id == seller_telegram_id,
            Listing.status == "rejected",
        )
    ) or 0
    return {
        "total": int(total),
        "pending": int(pending),
        "published": int(published),
        "rejected": int(rejected),
    }


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


async def unpublish_owned_listing(
    session: AsyncSession, *, listing_id: int, seller_telegram_id: int
) -> Listing | None:
    """Unpublish a seller-owned listing only when it is currently published."""
    result = await session.execute(
        select(Listing).where(
            Listing.id == listing_id,
            Listing.seller_telegram_id == seller_telegram_id,
            Listing.status == "published",
        )
    )
    listing = result.scalar_one_or_none()
    if listing is None:
        return None

    listing.status = "unpublished"
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


async def moderate_listing(
    session: AsyncSession, *, listing_id: int, decision: str
) -> Listing | None:
    """Approve or reject a listing that is still waiting for moderation."""
    transitions = {"approve": "published", "reject": "rejected"}
    if decision not in transitions:
        raise ValueError("Unsupported moderation decision")

    listing = await session.get(Listing, listing_id)
    if listing is None or listing.status != "pending":
        return None

    listing.status = transitions[decision]
    await session.commit()
    await session.refresh(listing)
    return listing


async def mark_listing_sold(session: AsyncSession, *, listing_id: int) -> Listing | None:
    """Mark a currently published listing as sold."""
    listing = await session.get(Listing, listing_id)
    if listing is None or listing.status != "published":
        return None

    listing.status = "sold"
    await session.commit()
    await session.refresh(listing)
    return listing


ADMIN_ROLES = frozenset({"user", "moderator", "admin"})


async def get_user_access(session: AsyncSession, telegram_id: int) -> UserAccess | None:
    """Get stored role and block status for a Telegram account."""
    return await session.get(UserAccess, telegram_id)


async def set_user_role(
    session: AsyncSession, *, telegram_id: int, role: str
) -> UserAccess:
    """Set a supported role; caller must enforce authorization."""
    if role not in ADMIN_ROLES:
        raise ValueError("Unsupported role")
    access = await session.get(UserAccess, telegram_id)
    if access is None:
        access = UserAccess(telegram_id=telegram_id, role=role)
        session.add(access)
    else:
        access.role = role
        access.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(access)
    return access


async def set_user_block(
    session: AsyncSession,
    *,
    telegram_id: int,
    blocked: bool,
    reason: str | None = None,
) -> UserAccess:
    """Set block state and optional reason; caller must enforce authorization."""
    access = await session.get(UserAccess, telegram_id)
    if access is None:
        access = UserAccess(telegram_id=telegram_id)
        session.add(access)
    access.is_blocked = blocked
    access.block_reason = (reason or "").strip()[:500] or None if blocked else None
    access.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(access)
    return access


async def get_admin_statistics(session: AsyncSession) -> dict[str, int]:
    """Return aggregate counts for the admin dashboard."""
    users = await session.scalar(select(func.count()).select_from(TelegramUser)) or 0
    listings = await session.scalar(select(func.count()).select_from(Listing)) or 0
    pending = await session.scalar(
        select(func.count()).select_from(Listing).where(Listing.status == "pending")
    ) or 0
    published = await session.scalar(
        select(func.count()).select_from(Listing).where(Listing.status == "published")
    ) or 0
    blocked = await session.scalar(
        select(func.count()).select_from(UserAccess).where(UserAccess.is_blocked.is_(True))
    ) or 0
    moderators = await session.scalar(
        select(func.count()).select_from(UserAccess).where(
            UserAccess.role.in_(("moderator", "admin"))
        )
    ) or 0
    return {
        "users": int(users),
        "listings": int(listings),
        "pending_listings": int(pending),
        "published_listings": int(published),
        "blocked_users": int(blocked),
        "staff": int(moderators),
    }
