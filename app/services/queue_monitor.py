"""Background monitor that times out conversations stuck in QUEUED_FOR_HUMAN."""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from app.config import settings
from app.core.handoff_engine import handoff_engine
from app.core.state_machine import ConversationState, Trigger
from app.db.engine import async_session_factory
from app.db.models.conversation import Conversation

logger = logging.getLogger(__name__)


async def check_queue_timeouts() -> int:
    """Check for conversations that have been queued too long and time them out.

    Returns the number of conversations timed out.
    """
    timeout_threshold = datetime.now(timezone.utc) - timedelta(
        seconds=settings.queue_timeout_seconds
    )
    timed_out = 0

    async with async_session_factory() as db:
        stmt = (
            select(Conversation.id)
            .where(
                Conversation.state == ConversationState.QUEUED_FOR_HUMAN.value,
                Conversation.queue_entered_at.isnot(None),
                Conversation.queue_entered_at < timeout_threshold,
            )
            .limit(50)  # Process in batches to avoid long locks
        )
        result = await db.execute(stmt)
        conv_ids = result.scalars().all()

    # Process each timeout in its own session/transaction
    for conv_id in conv_ids:
        try:
            async with async_session_factory() as db:
                await handoff_engine.process_trigger(
                    db=db,
                    conversation_id=conv_id,
                    trigger=Trigger.QUEUE_TIMEOUT,
                    metadata={
                        "reason": "Queue timeout exceeded",
                        "timeout_seconds": settings.queue_timeout_seconds,
                    },
                )
                await db.commit()
            timed_out += 1
            logger.info(
                "Queue timeout: ended conversation %s after %ds",
                conv_id,
                settings.queue_timeout_seconds,
            )
        except Exception:
            logger.warning(
                "Failed to timeout conversation %s", conv_id, exc_info=True
            )

    if timed_out:
        logger.info("Queue monitor: timed out %d conversations", timed_out)

    return timed_out


async def run_queue_monitor():
    """Background loop that checks queue timeouts periodically."""
    logger.info(
        "Queue monitor started (timeout=%ds, check interval=15s)",
        settings.queue_timeout_seconds,
    )
    while True:
        try:
            await asyncio.sleep(15)
            await check_queue_timeouts()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.warning("Queue monitor error", exc_info=True)
