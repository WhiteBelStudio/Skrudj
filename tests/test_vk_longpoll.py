"""Unit tests for VK Group Long Poll message dispatch."""

import pytest

from skrudj.vk_longpoll import HELP_TEXT, WELCOME_TEXT, VKLongPollClient


@pytest.mark.asyncio
async def test_start_command_sends_welcome_reply() -> None:
    client = VKLongPollClient(123, "test-token")
    sent: list[tuple[int, str]] = []

    async def capture(peer_id: int, text: str) -> None:
        sent.append((peer_id, text))

    client._send_message = capture  # type: ignore[method-assign]
    await client._handle_update(
        {
            "type": "message_new",
            "object": {
                "message": {"peer_id": 456, "from_id": 456, "out": 0, "text": "/start"}
            },
        }
    )

    assert sent == [(456, WELCOME_TEXT)]


@pytest.mark.asyncio
async def test_help_command_sends_help_reply() -> None:
    client = VKLongPollClient(123, "test-token")
    sent: list[tuple[int, str]] = []

    async def capture(peer_id: int, text: str) -> None:
        sent.append((peer_id, text))

    client._send_message = capture  # type: ignore[method-assign]
    await client._handle_update(
        {
            "type": "message_new",
            "object": {
                "message": {"peer_id": 456, "from_id": 456, "out": 0, "text": "/help"}
            },
        }
    )

    assert sent == [(456, HELP_TEXT)]


@pytest.mark.asyncio
async def test_regular_message_does_not_trigger_automatic_reply() -> None:
    client = VKLongPollClient(123, "test-token")
    sent: list[tuple[int, str]] = []

    async def capture(peer_id: int, text: str) -> None:
        sent.append((peer_id, text))

    client._send_message = capture  # type: ignore[method-assign]
    await client._handle_update(
        {
            "type": "message_new",
            "object": {
                "message": {"peer_id": 456, "from_id": 456, "out": 0, "text": "Привет"}
            },
        }
    )

    assert sent == []


@pytest.mark.asyncio
async def test_outgoing_message_is_ignored() -> None:
    client = VKLongPollClient(123, "test-token")
    sent: list[tuple[int, str]] = []

    async def capture(peer_id: int, text: str) -> None:
        sent.append((peer_id, text))

    client._send_message = capture  # type: ignore[method-assign]
    await client._handle_update(
        {
            "type": "message_new",
            "object": {
                "message": {"peer_id": 456, "from_id": -123, "out": 1, "text": "/start"}
            },
        }
    )

    assert sent == []
