"""WebSocket endpoint for real-time dashboard updates."""

from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.ws.manager import ws_manager

router = APIRouter()


@router.websocket("/ws/dashboard")
async def dashboard_websocket(
    ws: WebSocket,
    tenant_id: UUID = Query(...),
) -> None:
    await ws_manager.connect(ws, tenant_id)
    try:
        while True:
            # Keep connection alive; receive client messages (ping/pong, filters)
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(ws, tenant_id)
