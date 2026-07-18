import logging

from fastapi import WebSocket, WebSocketDisconnect


logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = {}
        self._connection_ids: dict[WebSocket, str] = {}
        self._next_connection_number = 1

    async def connect(
        self,
        *,
        client_id: int,
        websocket: WebSocket,
    ) -> str:
        if client_id not in self._connections:
            self._connections[client_id] = set()

        self._connections[client_id].add(websocket)
        connection_id = self._connection_ids.get(websocket)
        if connection_id is None:
            connection_id = f"ws-{self._next_connection_number}"
            self._next_connection_number += 1
            self._connection_ids[websocket] = connection_id
        return connection_id

    def disconnect(
        self,
        *,
        client_id: int,
        websocket: WebSocket,
    ) -> None:
        client_connections = self._connections.get(client_id)
        self._connection_ids.pop(websocket, None)

        if client_connections is None:
            return

        client_connections.discard(websocket)

        if not client_connections:
            self._connections.pop(client_id, None)

    async def send_to_client(
        self,
        *,
        client_id: int,
        payload: dict,
    ) -> None:
        client_connections = list(
            self._connections.get(client_id, set())
        )
        if not client_connections:
            return

        disconnected_connections: list[WebSocket] = []

        for websocket in client_connections:
            connection_id = self._connection_ids.get(websocket, "unknown")
            try:
                await websocket.send_json(payload)
            except (WebSocketDisconnect, RuntimeError) as exc:
                logger.warning(
                    "Dropping realtime websocket connection after send failure. connection_id=%s client_id=%s reason=socket_send_failure error=%s",
                    connection_id,
                    client_id,
                    type(exc).__name__,
                )
                disconnected_connections.append(websocket)
            except Exception:
                logger.exception(
                    "Unexpected realtime websocket send failure. connection_id=%s client_id=%s",
                    connection_id,
                    client_id,
                )
                disconnected_connections.append(websocket)

        for websocket in disconnected_connections:
            self.disconnect(
                client_id=client_id,
                websocket=websocket,
            )

    def connection_count(self, client_id: int) -> int:
        return len(self._connections.get(client_id, set()))

    def connection_ids(self, client_id: int) -> list[str]:
        return [
            self._connection_ids.get(websocket, "unknown")
            for websocket in self._connections.get(client_id, set())
        ]


connection_manager = ConnectionManager()
