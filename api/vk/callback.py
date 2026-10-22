"""Vercel HTTPS endpoint for VK Callback API events and community replies."""

from __future__ import annotations

import hmac
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


VK_API_VERSION = "5.199"


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _reply_text(message_text: str) -> str:
    normalized = message_text.strip().casefold()
    if normalized in {
        "привет",
        "здравствуйте",
        "добрый день",
        "начать",
        "/start",
        "меню",
        "помощь",
        "help",
    }:
        return (
            "Привет! 👋 Вы написали в сообщество «Скрудж Макдак».\n\n"
            "Я помогу с вопросами по объявлениям. Автоматическая обработка объявлений "
            "ещё настраивается. Напишите, что вас интересует, — сообщение появится "
            "в диалогах сообщества."
        )
    return (
        "Спасибо за сообщение! 👋 Оно поступило в диалоги сообщества «Скрудж Макдак».\n\n"
        "Автоматическая обработка объявлений пока настраивается. Пожалуйста, "
        "опишите вопрос одним сообщением."
    )


def _send_vk_reply(peer_id: int, message: str, token: str) -> bool:
    form = urlencode(
        {
            "access_token": token,
            "v": VK_API_VERSION,
            "peer_id": str(peer_id),
            "message": message,
            "random_id": str(secrets.randbelow(2_147_483_647)),
        }
    ).encode("utf-8")
    request = Request(
        "https://api.vk.com/method/messages.send",
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read(65536).decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return False
    return isinstance(payload, dict) and "response" in payload and "error" not in payload


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.rstrip("/") in {"/health/live", "/vk/callback", "/api/vk/callback"}:
            self._send(200, "ok", "text/plain; charset=utf-8")
            return
        self._send(404, "not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        group_id = _env("VK_GROUP_ID")
        confirmation_code = _env("VK_CONFIRMATION_CODE")
        expected_secret = _env("VK_CALLBACK_SECRET")
        if not group_id.isdigit() or not confirmation_code or not expected_secret:
            self._send(503, "VK callback is not configured.", "text/plain; charset=utf-8")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 262144:
                self._send(413, "invalid payload size", "text/plain; charset=utf-8")
                return
            payload = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self._send(400, "Invalid JSON payload.", "text/plain; charset=utf-8")
            return

        if not isinstance(payload, dict):
            self._send(400, "JSON payload must be an object.", "text/plain; charset=utf-8")
            return
        received_group = payload.get("group_id")
        if (
            isinstance(received_group, bool)
            or not isinstance(received_group, int)
            or received_group != int(group_id)
        ):
            self._send(403, "Unknown VK group.", "text/plain; charset=utf-8")
            return
        supplied_secret = payload.get("secret")
        if not isinstance(supplied_secret, str) or not hmac.compare_digest(
            supplied_secret, expected_secret
        ):
            self._send(403, "Invalid VK secret.", "text/plain; charset=utf-8")
            return

        event_type = payload.get("type")
        if event_type == "confirmation":
            self._send(200, confirmation_code, "text/plain; charset=utf-8")
            return
        if not isinstance(event_type, str):
            self._send(400, "Missing VK event type.", "text/plain; charset=utf-8")
            return

        # If an HTTPS forwarding target is configured, let the Pterodactyl app
        # handle the event. Otherwise this endpoint can reply directly via VK API.
        forward_url = _env("VK_FORWARD_URL")
        if forward_url:
            if not forward_url.startswith("https://"):
                self._send(503, "VK_FORWARD_URL must use HTTPS.", "text/plain; charset=utf-8")
                return
            request = Request(
                forward_url,
                data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=8) as response:
                    response_text = response.read(4096).decode("utf-8", errors="replace").strip()
                    if response.status < 200 or response.status >= 300 or response_text != "ok":
                        self._send(502, "VK event forwarding failed.", "text/plain; charset=utf-8")
                        return
            except (HTTPError, URLError, TimeoutError, OSError):
                self._send(502, "VK event forwarding failed.", "text/plain; charset=utf-8")
                return
            self._send(200, "ok", "text/plain; charset=utf-8")
            return

        if event_type == "message_new":
            event_object = payload.get("object")
            message = event_object.get("message", event_object) if isinstance(event_object, dict) else None
            if not isinstance(message, dict):
                self._send(400, "Invalid VK message event.", "text/plain; charset=utf-8")
                return
            from_id = message.get("from_id")
            peer_id = message.get("peer_id", from_id)
            if message.get("out") in (1, True) or (
                isinstance(from_id, int) and not isinstance(from_id, bool) and from_id < 0
            ):
                self._send(200, "ok", "text/plain; charset=utf-8")
                return
            if isinstance(peer_id, bool) or not isinstance(peer_id, int) or peer_id <= 0:
                self._send(400, "VK message has no valid peer_id.", "text/plain; charset=utf-8")
                return
            token = _env("VK_GROUP_TOKEN")
            if not token:
                self._send(503, "VK_GROUP_TOKEN is required for message replies.", "text/plain; charset=utf-8")
                return
            text = message.get("text", "")
            reply = _reply_text(text if isinstance(text, str) else "")
            if not _send_vk_reply(peer_id, reply, token):
                self._send(502, "VK API message reply failed.", "text/plain; charset=utf-8")
                return

        self._send(200, "ok", "text/plain; charset=utf-8")

    def _send(self, status: int, body: str, content_type: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        # Avoid logging payloads, tokens, or secret values.
        return
