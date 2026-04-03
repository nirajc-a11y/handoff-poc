"""Bridge between Redis Pub/Sub and WebSocket connections.

Spawns a background task that psubscribes to domain event patterns via Redis
and forwards matching events to tenant-scoped WebSocket clients.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.core.events import Event
from app.core.redis import get_redis
from app.ws.manager import WSConnectionManager

logger = logging.getLogger(__name__)

# Redis psubscribe patterns covering all domain events
_PATTERNS = [
    "conversation.*",
    "agent.*",
    "queue.*",
    "campaign.*",
    "channel.*",
]


class WSBroadcaster:
    def __init__(self, ws_manager: WSConnectionManager) -> None:
        self.ws_manager = ws_manager
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Spawn the Redis subscriber background task."""
        self._task = asyncio.create_task(self._subscribe_loop())

    async def _subscribe_loop(self) -> None:
        """Subscribe to Redis and relay events to WebSocket clients."""
        r = get_redis()
        pubsub = r.pubsub()
        await pubsub.psubscribe(*_PATTERNS)
        logger.info("WSBroadcaster subscribed to Redis patterns: %s", _PATTERNS)

        try:
            async for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue
                try:
                    event = Event.from_json(message["data"])
                    await self.ws_manager.broadcast_to_tenant(
                        event.tenant_id,
                        {
                            "type": event.topic,
                            "event_id": str(event.event_id),
                            "timestamp": event.timestamp.isoformat(),
                            "data": event.payload,
                        },
                    )
                except Exception:
                    logger.exception("Failed to relay Redis message to WebSocket")
        except asyncio.CancelledError:
            logger.info("WSBroadcaster subscribe loop cancelled")
        finally:
            await pubsub.punsubscribe(*_PATTERNS)
            await pubsub.aclose()

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
