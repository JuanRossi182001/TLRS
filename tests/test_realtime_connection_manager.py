import unittest

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


class ConnectionManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_connections_for_same_client_receive_event(self) -> None:
        manager = ConnectionManager()
        websocket_a = WebSocketStub()
        websocket_b = WebSocketStub()

        await manager.connect(client_id=4, websocket=websocket_a)
        await manager.connect(client_id=4, websocket=websocket_b)
        await manager.send_to_client(client_id=4, payload={"ok": True})

        self.assertEqual(websocket_a.messages, [{"ok": True}])
        self.assertEqual(websocket_b.messages, [{"ok": True}])
        self.assertEqual(manager.connection_count(4), 2)

    async def test_send_to_client_does_not_cross_client_boundaries(self) -> None:
        manager = ConnectionManager()
        websocket_a = WebSocketStub()
        websocket_b = WebSocketStub()

        await manager.connect(client_id=4, websocket=websocket_a)
        await manager.connect(client_id=5, websocket=websocket_b)
        await manager.send_to_client(client_id=4, payload={"client_id": 4})

        self.assertEqual(websocket_a.messages, [{"client_id": 4}])
        self.assertEqual(websocket_b.messages, [])

    async def test_closed_connection_is_removed_after_send_failure(self) -> None:
        manager = ConnectionManager()
        alive_websocket = WebSocketStub()
        closed_websocket = WebSocketStub(RuntimeError("closed"))

        await manager.connect(client_id=4, websocket=alive_websocket)
        await manager.connect(client_id=4, websocket=closed_websocket)
        await manager.send_to_client(client_id=4, payload={"ok": True})

        self.assertEqual(alive_websocket.messages, [{"ok": True}])
        self.assertEqual(manager.connection_count(4), 1)

    async def test_websocket_disconnect_is_removed(self) -> None:
        manager = ConnectionManager()
        failing_websocket = WebSocketStub(WebSocketDisconnect(code=1001))

        await manager.connect(client_id=4, websocket=failing_websocket)
        await manager.send_to_client(client_id=4, payload={"ok": True})

        self.assertEqual(manager.connection_count(4), 0)


if __name__ == "__main__":
    unittest.main()
