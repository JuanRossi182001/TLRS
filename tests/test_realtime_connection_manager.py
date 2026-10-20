import pytest
from fastapi import WebSocketDisconnect

from src.realtime.connection_manager import ConnectionManager


class WebSocketStub:
    def __init__(self, side_effect: Exception | None = None):
        self.side_effect = side_effect
        self.messages = []

    async def send_json(self, payload):
        if self.side_effect is not None:
            raise self.side_effect
        self.messages.append(payload)


@pytest.fixture
def connection_manager() -> ConnectionManager:
    """Provide isolated in-memory socket state for each test."""
    return ConnectionManager()


@pytest.mark.anyio
async def test_multiple_connections_for_same_client_receive_event(
    connection_manager: ConnectionManager,
) -> None:
    websocket_a = WebSocketStub()
    websocket_b = WebSocketStub()

    await connection_manager.connect(client_id=4, websocket=websocket_a)
    await connection_manager.connect(client_id=4, websocket=websocket_b)
    await connection_manager.send_to_client(client_id=4, payload={"ok": True})

    assert websocket_a.messages == [{"ok": True}]
    assert websocket_b.messages == [{"ok": True}]
    assert connection_manager.connection_count(4) == 2


@pytest.mark.anyio
async def test_send_to_client_does_not_cross_client_boundaries(
    connection_manager: ConnectionManager,
) -> None:
    websocket_a = WebSocketStub()
    websocket_b = WebSocketStub()

    await connection_manager.connect(client_id=4, websocket=websocket_a)
    await connection_manager.connect(client_id=5, websocket=websocket_b)
    await connection_manager.send_to_client(client_id=4, payload={"client_id": 4})

    assert websocket_a.messages == [{"client_id": 4}]
    assert websocket_b.messages == []


@pytest.mark.anyio
async def test_closed_connection_is_removed_after_send_failure(
    connection_manager: ConnectionManager,
) -> None:
    alive_websocket = WebSocketStub()
    closed_websocket = WebSocketStub(RuntimeError("closed"))

    await connection_manager.connect(client_id=4, websocket=alive_websocket)
    await connection_manager.connect(client_id=4, websocket=closed_websocket)
    await connection_manager.send_to_client(client_id=4, payload={"ok": True})

    assert alive_websocket.messages == [{"ok": True}]
    assert connection_manager.connection_count(4) == 1


@pytest.mark.anyio
async def test_websocket_disconnect_is_removed(
    connection_manager: ConnectionManager,
) -> None:
    failing_websocket = WebSocketStub(WebSocketDisconnect(code=1001))

    await connection_manager.connect(client_id=4, websocket=failing_websocket)
    await connection_manager.send_to_client(client_id=4, payload={"ok": True})

    assert connection_manager.connection_count(4) == 0
