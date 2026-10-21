"""Tests for the VK Callback API endpoint."""

from aiohttp.test_utils import TestClient, TestServer
import pytest

from skrudj.config import Settings
from skrudj.vk_callback import create_vk_callback_app


@pytest.fixture
def vk_settings() -> Settings:
    return Settings(
        _env_file=None,
        vk_group_id=987654,
        vk_group_token="test-group-secret",
        vk_confirmation_code="confirm-me",
    )


@pytest.mark.asyncio
async def test_health_endpoint_does_not_expose_secrets(vk_settings: Settings) -> None:
    async with TestClient(TestServer(create_vk_callback_app(vk_settings))) as client:
        response = await client.get("/health/live")

    assert response.status == 200
    assert await response.json() == {"status": "ok", "service": "vk-callback"}
    assert "test-group-secret" not in await response.text()


@pytest.mark.asyncio
async def test_confirmation_returns_configured_plain_text_code(vk_settings: Settings) -> None:
    async with TestClient(TestServer(create_vk_callback_app(vk_settings))) as client:
        response = await client.post(
            "/vk/callback",
            json={
                "type": "confirmation",
                "group_id": 987654,
                "secret": "test-group-secret",
                "object": {},
            },
        )

    assert response.status == 200
    assert await response.text() == "confirm-me"


@pytest.mark.asyncio
async def test_valid_event_is_acknowledged_and_dispatched(vk_settings: Settings) -> None:
    received: list[dict] = []

    async def handler(event: dict) -> None:
        received.append(event)

    payload = {
        "type": "message_new",
        "group_id": 987654,
        "secret": "test-group-secret",
        "object": {"message": {"text": "Привет"}},
    }
    async with TestClient(TestServer(create_vk_callback_app(vk_settings, handler))) as client:
        response = await client.post("/vk/callback", json=payload)

    assert response.status == 200
    assert await response.text() == "ok"
    assert received == [payload]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        ({"type": "message_new", "group_id": 123, "secret": "test-group-secret"}, 403),
        ({"type": "message_new", "group_id": 987654, "secret": "wrong"}, 403),
        ({"type": "message_new", "group_id": 987654}, 403),
        ({"group_id": 987654, "secret": "test-group-secret"}, 400),
    ],
)
async def test_invalid_callback_requests_are_rejected(
    vk_settings: Settings,
    payload: dict,
    expected_status: int,
) -> None:
    async with TestClient(TestServer(create_vk_callback_app(vk_settings))) as client:
        response = await client.post("/vk/callback", json=payload)

    assert response.status == expected_status


@pytest.mark.asyncio
async def test_callback_is_unavailable_without_required_configuration() -> None:
    settings = Settings(_env_file=None)
    async with TestClient(TestServer(create_vk_callback_app(settings))) as client:
        response = await client.post(
            "/vk/callback",
            json={"type": "confirmation", "group_id": 1, "secret": "secret"},
        )

    assert response.status == 503


@pytest.mark.asyncio
async def test_handler_failure_returns_server_error(vk_settings: Settings) -> None:
    async def handler(event: dict) -> None:
        raise RuntimeError("simulated failure")

    async with TestClient(TestServer(create_vk_callback_app(vk_settings, handler))) as client:
        response = await client.post(
            "/vk/callback",
            json={
                "type": "message_new",
                "group_id": 987654,
                "secret": "test-group-secret",
                "object": {},
            },
        )

    assert response.status == 500
