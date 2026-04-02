"""Bridge between the in-process EventBus and WebSocket connections."""

from app.core.events import Event, EventBus
from app.ws.manager import WSConnectionManager


class WSBroadcaster:
    def __init__(self, event_bus: EventBus, ws_manager: WSConnectionManager) -> None:
        self.event_bus = event_bus
        self.ws_manager = ws_manager

    def start(self) -> None:
        """Subscribe to all domain event patterns."""
        self.event_bus.subscribe("conversation.*", self._on_event)
        self.event_bus.subscribe("agent.*", self._on_event)
        self.event_bus.subscribe("queue.*", self._on_event)
        self.event_bus.subscribe("campaign.*", self._on_event)
        self.event_bus.subscribe("channel.*", self._on_event)

    async def _on_event(self, event: Event) -> None:
        await self.ws_manager.broadcast_to_tenant(
            event.tenant_id,
            {
                "type": event.topic,
                "event_id": str(event.event_id),
                "timestamp": event.timestamp.isoformat(),
                "data": event.payload,
            },
        )
