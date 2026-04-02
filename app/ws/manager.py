"""Tenant-scoped WebSocket connection manager."""

from collections import defaultdict
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect


class WSConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[UUID, set[WebSocket]] = defaultdict(set)

    async def connect(self, ws: WebSocket, tenant_id: UUID) -> None:
        await ws.accept()
        self._rooms[tenant_id].add(ws)

    async def disconnect(self, ws: WebSocket, tenant_id: UUID) -> None:
        self._rooms[tenant_id].discard(ws)
        if not self._rooms[tenant_id]:
            del self._rooms[tenant_id]

    async def broadcast_to_tenant(self, tenant_id: UUID, event: dict) -> None:
        dead: list[WebSocket] = []
        for ws in self._rooms.get(tenant_id, set()):
            try:
                await ws.send_json(event)
            except (WebSocketDisconnect, RuntimeError):
                dead.append(ws)
        for ws in dead:
            self._rooms[tenant_id].discard(ws)

    @property
    def connection_count(self) -> int:
        return sum(len(conns) for conns in self._rooms.values())


# Module-level singleton
ws_manager = WSConnectionManager()
