"""VK Callback API endpoint for the Skrudj marketplace."""

from __future__ import annotations

import hmac
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

from skrudj.config import Settings

logger = logging.getLogger(__name__)

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


async def _ignore_event(event: dict[str, Any]) -> None:
    """Default safe event handler until marketplace event processing is wired in."""


def create_vk_callback_app(
    settings: Settings,
    event_handler: EventHandler | None = None,
) -> web.Application:
    """Create a minimal VK Callback API app with secret and group validation.

    VK requires a plain-text confirmation code for the `confirmation` event and
    the literal `ok` for accepted events. Invalid requests receive HTTP 403.
    """
    app = web.Application(client_max_size=256 * 1024)
    app[web.AppKey("vk_settings", Settings)] = settings
    app[web.AppKey("vk_event_handler", EventHandler)] = event_handler or _ignore_event
    app.router.add_get("/health/live", _health_live)
    app.router.add_post("/vk/callback", handle_vk_callback)
    return app


async def _health_live(request: web.Request) -> web.Response:
    """Expose a minimal liveness endpoint without revealing configuration."""
    return web.json_response({"status": "ok", "service": "vk-callback"})


async def handle_vk_callback(request: web.Request) -> web.Response:
    """Validate and acknowledge one VK Callback API event."""
    settings: Settings = request.app[web.AppKey("vk_settings", Settings)]
    event_handler: EventHandler = request.app[web.AppKey("vk_event_handler", EventHandler)]

    if settings.vk_group_id is None or not settings.vk_confirmation_code:
        logger.error("VK Callback API received a request before configuration was complete.")
        raise web.HTTPServiceUnavailable(text="VK callback is not configured.")

    try:
        payload = await request.json()
    except (ValueError, web.HTTPBadRequest):
        raise web.HTTPBadRequest(text="Invalid JSON payload.") from None

    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="JSON payload must be an object.")

    group_id = payload.get("group_id")
    if isinstance(group_id, bool) or not isinstance(group_id, int) or group_id != settings.vk_group_id:
        raise web.HTTPForbidden(text="Unknown VK group.")

    supplied_secret = payload.get("secret")
    expected_secret = settings.vk_group_token.get_secret_value() if settings.vk_group_token else ""
    if not expected_secret or not isinstance(supplied_secret, str):
        raise web.HTTPForbidden(text="Invalid VK secret.")
    if not hmac.compare_digest(supplied_secret, expected_secret):
        raise web.HTTPForbidden(text="Invalid VK secret.")

    event_type = payload.get("type")
    if not isinstance(event_type, str):
        raise web.HTTPBadRequest(text="Missing VK event type.")

    if event_type == "confirmation":
        return web.Response(text=settings.vk_confirmation_code, content_type="text/plain")

    event = payload.get("object", {})
    if not isinstance(event, dict):
        raise web.HTTPBadRequest(text="VK event object must be an object.")

    try:
        await event_handler(payload)
    except Exception:
        logger.exception("VK callback event handler failed for event type %s.", event_type)
        raise web.HTTPInternalServerError(text="VK event processing failed.") from None

    return web.Response(text="ok", content_type="text/plain")
