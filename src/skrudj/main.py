"""Skrudj process entry point."""

import asyncio
import logging
import sys
from pathlib import Path

from aiohttp import web

from skrudj.config import Settings, get_settings
from skrudj.database import initialize_database, make_engine, make_session_factory
from skrudj.telegram_bot import run_telegram_bot
from skrudj.vk_messages import handle_vk_event
from skrudj.vk_callback import create_vk_callback_app


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


def _vk_callback_is_configured(settings: Settings) -> bool:
    """Return whether all required VK Callback API settings are present."""
    return (
        settings.vk_group_id is not None
        and settings.vk_group_token is not None
        and bool(settings.vk_group_token.get_secret_value())
        and settings.vk_callback_secret is not None
        and bool(settings.vk_callback_secret.get_secret_value())
        and bool(settings.vk_confirmation_code)
    )


async def run_vk_callback_server(settings: Settings) -> None:
    """Run the VK Callback API server until the application shuts down."""
    app = create_vk_callback_app(
        settings,
        event_handler=lambda event: handle_vk_event(event, settings),
    )
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(
        runner,
        host=settings.vk_callback_host,
        port=settings.vk_callback_port,
    )
    try:
        await site.start()
        logging.getLogger("skrudj.vk_callback").info(
            "VK Callback API listening on %s:%s",
            settings.vk_callback_host,
            settings.vk_callback_port,
        )
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


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

        vk_enabled = _vk_callback_is_configured(settings)
        if settings.telegram_bot_token is None and not vk_enabled:
            logger.warning(
                "Neither TELEGRAM_BOT_TOKEN nor complete VK Callback configuration is set; "
                "database is ready, but no bot or callback server was started."
            )
            return

        tasks = []
        if settings.telegram_bot_token is not None:
            session_factory = make_session_factory(engine)
            tasks.append(
                run_telegram_bot(
                    settings.telegram_bot_token.get_secret_value(),
                    session_factory,
                )
            )
        if vk_enabled:
            tasks.append(run_vk_callback_server(settings))
        elif (
            settings.vk_group_id is not None
            or settings.vk_callback_secret is not None
            or settings.vk_confirmation_code is not None
        ):
            logger.warning(
                "VK Callback settings are incomplete; VK server was not started."
            )

        if len(tasks) == 1:
            await tasks[0]
        else:
            await asyncio.gather(*tasks)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
