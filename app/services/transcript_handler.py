"""Background service: persists LiveKit transcripts to the DB via Redis pub/sub.

The LiveKit agent (a separate subprocess) publishes to the ``transcript.added``
Redis channel instead of opening its own DB connections.  This handler:

1. Subscribes to ``transcript.added``
2. Saves a ``Message`` record (sender_type, content)
3. Publishes ``conversation.message_added`` so WSBroadcaster forwards it to the frontend
"""

from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

logger = logging.getLogger(__name__)

_MAX_BACKOFF = 30.0


async def run_transcript_handler() -> None:
    """Long-running coroutine — subscribe to Redis and persist transcripts."""
    backoff = 1.0

    while True:
        pubsub = None
        try:
            from app.core.redis import get_redis
            from app.db.engine import async_session_factory
            from app.db.models.message import Message
            from app.core.events import event_bus, Event

            r = get_redis()
            pubsub = r.pubsub()
            await pubsub.subscribe("transcript.added")
            logger.info("TranscriptHandler subscribed to Redis channel 'transcript.added'")
            backoff = 1.0

            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                try:
                    data = json.loads(msg["data"])
                    conv_id = data.get("conversation_id")
                    tenant_id = data.get("tenant_id")
                    sender_type = data.get("sender_type")
                    content = (data.get("content") or "").strip()

                    if not (conv_id and tenant_id and sender_type and content):
                        continue

                    async with async_session_factory() as db:
                        message = Message(
                            tenant_id=UUID(tenant_id),
                            conversation_id=UUID(conv_id),
                            sender_type=sender_type,
                            content_type="text",
                            content=content,
                            metadata_={"source": "livekit_agent"},
                        )
                        db.add(message)
                        await db.commit()

                    await event_bus.publish(Event(
                        topic="conversation.message_added",
                        tenant_id=UUID(tenant_id),
                        payload={"conversation_id": conv_id},
                    ))
                    logger.debug(
                        "Transcript saved: conv=%s sender=%s len=%d",
                        conv_id, sender_type, len(content),
                    )

                except Exception:
                    logger.exception("TranscriptHandler: failed to process message")

        except asyncio.CancelledError:
            logger.info("TranscriptHandler cancelled")
            break
        except Exception:
            logger.exception(
                "TranscriptHandler Redis connection lost, reconnecting in %.1fs", backoff
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe("transcript.added")
                    await pubsub.aclose()
                except Exception:
                    pass
