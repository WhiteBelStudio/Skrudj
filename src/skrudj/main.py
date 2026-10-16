"""Skrudj process entry point."""

import asyncio
import logging
import sys
from pathlib import Path

from skrudj.config import get_settings
from skrudj.database import initialize_database, make_engine, make_session_factory
from skrudj.telegram_bot import run_telegram_bot


def configure_logging(level: str) -> None:
    """Configure concise standard logging without exposing secret values."""
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger("skrudj")

    if settings.database_url.startswith("sqlite+"):
        database_path = settings.database_url.split("///", maxsplit=1)[-1]
        if database_path and database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    engine = make_engine(settings.database_url)
    try:
        await initialize_database(engine)
        logger.info("Database initialized.")

        if settings.telegram_bot_token is None:
            logger.warning(
                "TELEGRAM_BOT_TOKEN is not configured; database is ready, "
                "but Telegram polling was not started."
            )
            return

        session_factory = make_session_factory(engine)
        await run_telegram_bot(
            settings.telegram_bot_token.get_secret_value(),
            session_factory,
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
