"""Tests for VK community message parsing and reply selection."""

from skrudj.vk_messages import build_vk_reply


def test_greeting_gets_welcome_reply() -> None:
    result = build_vk_reply(
        {
            "type": "message_new",
            "object": {
                "message": {
                    "from_id": 12345,
                    "peer_id": 12345,
                    "text": "Привет",
                    "out": 0,
                }
            },
        }
    )

    assert result is not None
    peer_id, reply = result
    assert peer_id == 12345
    assert "Скрудж Макдак" in reply
    assert "Привет" in reply


def test_regular_message_gets_acknowledgement() -> None:
    result = build_vk_reply(
        {
            "type": "message_new",
            "object": {
                "message": {
                    "from_id": 12345,
                    "peer_id": 12345,
                    "text": "Как разместить объявление?",
                    "out": 0,
                }
            },
        }
    )

    assert result is not None
    assert result[0] == 12345
    assert "Спасибо за сообщение" in result[1]


def test_outgoing_message_is_ignored() -> None:
    result = build_vk_reply(
        {
            "type": "message_new",
            "object": {
                "message": {
                    "from_id": -987654,
                    "peer_id": 12345,
                    "text": "Bot reply",
                    "out": 1,
                }
            },
        }
    )

    assert result is None


def test_non_message_event_is_ignored() -> None:
    assert build_vk_reply({"type": "group_join", "object": {}}) is None


def test_invalid_peer_id_is_ignored() -> None:
    assert build_vk_reply(
        {
            "type": "message_new",
            "object": {"message": {"from_id": 123, "peer_id": "bad", "text": "hello"}},
        }
    ) is None
