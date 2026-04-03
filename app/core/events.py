"""Async event bus backed by Redis Pub/Sub.

Public API is unchanged from the original in-process version:
    event_bus.publish(event)   — serialises & publishes to Redis channel
    event_bus.subscribe(...)   — only used by WSBroadcaster (kept for compat)

The WSBroadcaster now uses `RedisSubscriber` to listen via Redis psubscribe.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.core.redis import get_redis

logger = logging.getLogger(__name__)


@dataclass
class Event:
    topic: str
    tenant_id: UUID
    payload: dict
    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_json(self) -> str:
        return json.dumps(
            {
                "topic": self.topic,
                "tenant_id": str(self.tenant_id),
                "payload": self.payload,
                "event_id": str(self.event_id),
                "timestamp": self.timestamp.isoformat(),
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "Event":
        d = json.loads(raw)
        return cls(
            topic=d["topic"],
            tenant_id=UUID(d["tenant_id"]),
            payload=d["payload"],
            event_id=UUID(d["event_id"]),
            timestamp=datetime.fromisoformat(d["timestamp"]),
        )


class EventBus:
    """Publishes events to Redis Pub/Sub channels."""

    async def publish(self, event: Event) -> None:
        try:
            r = get_redis()
            await r.publish(event.topic, event.to_json())
        except Exception:
            logger.exception(
                "Failed to publish event %s (topic=%s)", event.event_id, event.topic
            )


# Module-level singleton
event_bus = EventBus()
