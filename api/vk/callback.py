"""Vercel HTTPS bridge for VK Callback API confirmation and forwarding.

Configure VK_GROUP_ID, VK_CONFIRMATION_CODE and VK_CALLBACK_SECRET in Vercel.
For non-confirmation events, set VK_FORWARD_URL to a publicly reachable HTTPS
endpoint that accepts the original VK JSON payload (for example, a secured
Skrudj callback endpoint).
"""
from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.rstrip("/")
        if path in {"/health/live", "/vk/callback", "/api/vk/callback"}:
            # Safe diagnostics: report presence only; never expose secret values.
            if path == "/health/live":
                status = {
                    "status": "ok",
                    "service": "vk-callback-bridge",
                    "group_id_configured": bool(_env("VK_GROUP_ID").isdigit()),
                    "confirmation_code_configured": bool(_env("VK_CONFIRMATION_CODE")),
                    "callback_secret_configured": bool(_env("VK_CALLBACK_SECRET")),
                    "forward_url_configured": _env("VK_FORWARD_URL").startswith("https://"),
                }
                self._send(200, json.dumps(status), "application/json; charset=utf-8")
            else:
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
        if isinstance(received_group, bool) or not isinstance(received_group, int) or received_group != int(group_id):
            self._send(403, "Unknown VK group.", "text/plain; charset=utf-8")
            return
        supplied_secret = payload.get("secret")
        if not isinstance(supplied_secret, str) or not hmac.compare_digest(supplied_secret, expected_secret):
            self._send(403, "Invalid VK secret.", "text/plain; charset=utf-8")
            return

        event_type = payload.get("type")
        if event_type == "confirmation":
            self._send(200, confirmation_code, "text/plain; charset=utf-8")
            return
        if not isinstance(event_type, str):
            self._send(400, "Missing VK event type.", "text/plain; charset=utf-8")
            return

        forward_url = _env("VK_FORWARD_URL")
        if not forward_url.startswith("https://"):
            self._send(503, "VK event forwarding is not configured.", "text/plain; charset=utf-8")
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
