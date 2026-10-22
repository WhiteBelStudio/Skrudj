"""Minimal incoming-message handling for the VK community."""

from __future__ import annotations

import logging
import secrets
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from skrudj.config import Settings

logger = logging.getLogger(__name__)

VK_API_VERSION = "5.199"


def build_vk_reply(event: dict[str, Any]) -> tuple[int, str] | None:
    """Return a peer ID and reply text for a supported incoming message event."""
    if event.get("type") != "message_new":
        return None

    event_object = event.get("object")
    if not isinstance(event_object, dict):
        return None

    message = event_object.get("message", event_object)
    if not isinstance(message, dict):
        return None

    if message.get("out") in (1, True):
        return None

    from_id = message.get("from_id")
    peer_id = message.get("peer_id", from_id)
    if (
        isinstance(peer_id, bool)
        or not isinstance(peer_id, int)
        or peer_id <= 0
        or isinstance(from_id, bool)
        or (from_id is not None and not isinstance(from_id, int))
        or (isinstance(from_id, int) and from_id < 0)
    ):
        return None

    incoming_text = message.get("text", "")
    normalized = incoming_text.strip().casefold() if isinstance(incoming_text, str) else ""

    greetings = {
        "привет", "здравствуйте", "добрый день", "начать", "/start", "меню", "помощь", "help"
    }
    if normalized in greetings:
        reply = (
            "Привет! 👋 Вы написали в сообщество «Скрудж Макдак».\n\n"
            "Я помогу с вопросами по объявлениям. Автоматическая обработка объявлений "
            "ещё настраивается. Напишите, что вас интересует, — сообщение появится "
            "в диалогах сообщества."
        )
    else:
        reply = (
            "Спасибо за сообщение! 👋 Оно поступило в диалоги сообщества «Скрудж Макдак».\n\n"
            "Автоматическая обработка объявлений пока настраивается. Пожалуйста, "
            "опишите вопрос одним сообщением."
        )

    return peer_id, reply


async def handle_vk_event(event: dict[str, Any], settings: Settings) -> None:
    """Respond to supported incoming VK messages using the community access token."""
    reply_data = build_vk_reply(event)
    if reply_data is None:
        return

    if settings.vk_group_token is None or not settings.vk_group_token.get_secret_value():
        raise RuntimeError("VK_GROUP_TOKEN is required to reply to community messages.")

    peer_id, reply_text = reply_data
    form = {
        "access_token": settings.vk_group_token.get_secret_value(),
        "v": VK_API_VERSION,
        "peer_id": str(peer_id),
        "message": reply_text,
        "random_id": str(secrets.randbelow(2_147_483_647)),
    }

    try:
        async with ClientSession(timeout=ClientTimeout(total=10)) as session:
            async with session.post(
                "https://api.vk.com/method/messages.send", data=form
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
    except (ClientError, TimeoutError, ValueError) as exc:
        logger.warning("VK messages.send request failed (%s).", type(exc).__name__)
        raise RuntimeError("VK messages.send request failed.") from None

    if not isinstance(payload, dict):
        raise RuntimeError("VK API returned an unexpected response.")
    api_error = payload.get("error")
    if isinstance(api_error, dict):
        error_code = api_error.get("error_code", "unknown")
        logger.warning("VK API rejected messages.send (error code %s).", error_code)
        raise RuntimeError(f"VK API rejected messages.send (error code {error_code}).")

    logger.info("VK community reply sent to peer_id=%s.", peer_id)
