# In-process async event bus with glob-style topic matching.
# Subscribers register a fnmatch pattern; publish fans out to all matches.

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from typing import Awaitable, Callable
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

Subscriber = Callable[["Event"], Awaitable[None]]


@dataclass
class Event:
    topic: str
    tenant_id: UUID
    payload: dict
    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[tuple[str, Subscriber]] = []

    def subscribe(self, topic_pattern: str, handler: Subscriber) -> None:
        self._subscribers.append((topic_pattern, handler))

    async def publish(self, event: Event) -> None:
        tasks: list[asyncio.Task] = []
        for pattern, handler in self._subscribers:
            if fnmatch(event.topic, pattern):
                tasks.append(asyncio.create_task(self._safe_call(handler, event)))
        if tasks:
            await asyncio.gather(*tasks)

    @staticmethod
    async def _safe_call(handler: Subscriber, event: Event) -> None:
        try:
            await handler(event)
        except Exception:
            logger.exception(
                "Event handler %s failed for topic %r (event_id=%s)",
                handler.__qualname__,
                event.topic,
                event.event_id,
            )


# Module-level singleton
event_bus = EventBus()
