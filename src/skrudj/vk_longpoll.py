"""VK Group Long Poll receiver for installations without a public HTTPS callback URL."""

from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Any

import aiohttp

from skrudj.config import Settings

logger = logging.getLogger(__name__)

VK_API = "https://api.vk.com/method"
VK_API_VERSION = "5.199"
WELCOME_TEXT = (
    "🦆 Привет! Это «Скрудж Макдак» — барахолка WhiteBelStudio.\n\n"
    "VK-интеграция сейчас подключена в базовом режиме.\n"
    "Напишите /help, чтобы посмотреть доступные команды.\n\n"
    "Полный каталог и создание объявлений пока доступны в Telegram-боте проекта."
)
HELP_TEXT = (
    "ℹ️ Команды «Скрудж Макдак»\n\n"
    "/start — приветствие.\n"
    "/help — эта справка.\n\n"
    "VK-приём сообщений работает в базовом режиме; каталог и публикация объявлений "
    "через VK ещё не подключены."
)


class VKAPIError(RuntimeError):
    """Raised when VK API reports an error."""


class VKLongPollClient:
    """Receive group messages via VK Long Poll and send basic command replies."""

    def __init__(
        self,
        group_id: int,
        token: str,
        *,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        if group_id <= 0:
            raise ValueError("VK group ID must be positive.")
        if not token.strip():
            raise ValueError("VK group token must not be empty.")
        self.group_id = group_id
        self.token = token.strip()
        self._session = session
        self._owns_session = session is None

    async def run(self) -> None:
        """Keep polling, retrying transient network errors with a short delay."""
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=35, connect=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        logger.info("VK Group Long Poll receiver starting for group %s.", self.group_id)
        try:
            while True:
                try:
                    await self._poll_forever()
                except asyncio.CancelledError:
                    raise
                except (aiohttp.ClientError, asyncio.TimeoutError, VKAPIError, ValueError):
                    logger.exception("VK Long Poll cycle failed; retrying in 5 seconds.")
                    await asyncio.sleep(5)
        finally:
            if self._owns_session and self._session is not None:
                await self._session.close()
                self._session = None

    async def _api(self, method: str, **params: Any) -> dict[str, Any]:
        assert self._session is not None
        data = {
            "access_token": self.token,
            "v": VK_API_VERSION,
            **params,
        }
        async with self._session.post(f"{VK_API}/{method}", data=data) as response:
            response.raise_for_status()
            body = await response.json(content_type=None)
        if not isinstance(body, dict):
            raise VKAPIError(f"VK API {method} returned an invalid response.")
        if "error" in body:
            error = body["error"]
            code = error.get("error_code") if isinstance(error, dict) else "unknown"
            message = error.get("error_msg", "unknown error") if isinstance(error, dict) else "unknown error"
            raise VKAPIError(f"VK API {method} failed (code {code}): {message}")
        result = body.get("response")
        if not isinstance(result, dict):
            raise VKAPIError(f"VK API {method} did not return an object.")
        return result

    async def _get_longpoll_server(self) -> tuple[str, str, str]:
        result = await self._api("groups.getLongPollServer", group_id=self.group_id)
        server, key, ts = result.get("server"), result.get("key"), result.get("ts")
        if not all(isinstance(value, (str, int)) and str(value) for value in (server, key, ts)):
            raise VKAPIError("VK returned incomplete Long Poll server settings.")
        return str(server), str(key), str(ts)

    async def _poll_forever(self) -> None:
        assert self._session is not None
        server, key, ts = await self._get_longpoll_server()
        while True:
            params = {"act": "a_check", "key": key, "ts": ts, "wait": 25, "version": 3}
            async with self._session.get(server, params=params) as response:
                response.raise_for_status()
                body = await response.json(content_type=None)
            if not isinstance(body, dict):
                raise VKAPIError("VK Long Poll returned an invalid response.")
            failed = body.get("failed")
            if failed:
                if failed == 1 and body.get("ts") is not None:
                    ts = str(body["ts"])
                    continue
                # Codes 2 and 3 mean the key or server expired; obtain fresh settings.
                logger.warning("VK Long Poll requested server refresh (code %s).", failed)
                return
            if body.get("ts") is not None:
                ts = str(body["ts"])
            updates = body.get("updates", [])
            if not isinstance(updates, list):
                raise VKAPIError("VK Long Poll updates field is not a list.")
            for update in updates:
                if isinstance(update, dict):
                    await self._handle_update(update)

    async def _handle_update(self, update: dict[str, Any]) -> None:
        if update.get("type") != "message_new":
            return
        obj = update.get("object")
        message = obj.get("message") if isinstance(obj, dict) else None
        if not isinstance(message, dict):
            return
        if message.get("out") == 1:
            return
        peer_id = message.get("peer_id")
        if isinstance(peer_id, bool) or not isinstance(peer_id, int) or peer_id <= 0:
            return
        text = message.get("text", "")
        text = text.strip() if isinstance(text, str) else ""
        command = text.split(maxsplit=1)[0].lower() if text else ""
        if command in {"/start", "начать", "старт"}:
            reply = WELCOME_TEXT
        elif command in {"/help", "помощь", "помоги"}:
            reply = HELP_TEXT
        else:
            # Avoid spamming users: only commands trigger automatic replies.
            return
        await self._send_message(peer_id, reply)

    async def _send_message(self, peer_id: int, text: str) -> None:
        await self._api(
            "messages.send",
            peer_id=peer_id,
            random_id=secrets.randbelow(2_000_000_000),
            message=text,
        )


async def run_vk_longpoll(settings: Settings) -> None:
    """Start VK Long Poll when both the group ID and community token are configured."""
    if settings.vk_group_id is None or settings.vk_group_token is None:
        raise ValueError("VK_GROUP_ID and VK_GROUP_TOKEN are required for VK Long Poll.")
    client = VKLongPollClient(
        settings.vk_group_id,
        settings.vk_group_token.get_secret_value(),
    )
    await client.run()
