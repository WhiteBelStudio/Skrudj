"""Skrudj process entry point."""

import asyncio
import logging
import sys
from pathlib import Path

from skrudj.config import get_settings


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

    logger.info("Skrudj configuration loaded (environment=%s).", settings.app_env)
    logger.info(
        "Startup scaffold only: integrations and database migrations are not implemented yet."
    )


if __name__ == "__main__":
    asyncio.run(run())
