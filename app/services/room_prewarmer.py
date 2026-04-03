"""LiveKit room pre-warmer — creates rooms during IVR to eliminate dispatch delay.

The CALL_FLOW_ANALYSIS showed a 2.74s LiveKit job dispatch delay after DTMF.
By pre-creating the room during IVR (while the caller navigates the menu ~20s),
the room is already waiting when DTMF arrives. The agent worker can be
pre-dispatched to the room, cutting the delay to near-zero.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional

from livekit import api as lk_api

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class PrewarmedRoom:
    room_name: str
    tenant_id: str
    conversation_id: str
    language: str
    company_name: str
    created_at: float


class RoomPrewarmer:
    """Creates LiveKit rooms during IVR phase so they're ready when DTMF arrives.

    Keyed by conversation_id. Rooms auto-expire via LiveKit's empty_timeout.
    """

    def __init__(self) -> None:
        self._rooms: dict[str, PrewarmedRoom] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def prewarm(
        self,
        conversation_id: str,
        tenant_id: str,
        language: str,
        company_name: str,
    ) -> Optional[PrewarmedRoom]:
        """Create room + dispatch agent. Called as background task during IVR.

        Idempotent — safe to call multiple times for same conversation.
        """
        if conversation_id in self._rooms:
            return self._rooms[conversation_id]

        if conversation_id not in self._locks:
            self._locks[conversation_id] = asyncio.Lock()

        async with self._locks[conversation_id]:
            # Double-check after acquiring lock
            if conversation_id in self._rooms:
                return self._rooms[conversation_id]

            room_name = f"room-{conversation_id}"
            metadata = json.dumps({
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "language": language,
                "company_name": company_name,
            })

            room_api = lk_api.LiveKitAPI(
                url=settings.livekit_url,
                api_key=settings.livekit_api_key,
                api_secret=settings.livekit_api_secret,
            )
            try:
                await asyncio.wait_for(
                    room_api.room.create_room(
                        lk_api.CreateRoomRequest(
                            name=room_name,
                            metadata=metadata,
                            empty_timeout=60,  # auto-delete if nobody joins within 60s
                            max_participants=3,  # bridge + agent + optional supervisor
                        )
                    ),
                    timeout=5.0,
                )

                prewarmed = PrewarmedRoom(
                    room_name=room_name,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    language=language,
                    company_name=company_name,
                    created_at=asyncio.get_event_loop().time(),
                )
                self._rooms[conversation_id] = prewarmed
                logger.info(
                    "Room pre-warmed: %s (conv=%s, tenant=%s)",
                    room_name, conversation_id, tenant_id,
                )
                return prewarmed

            except asyncio.TimeoutError:
                logger.error("Room pre-warm timed out (conv=%s)", conversation_id)
                return None
            except Exception:
                logger.warning("Room pre-warm failed (non-fatal, conv=%s)", conversation_id, exc_info=True)
                return None
            finally:
                await room_api.aclose()

    def consume(self, conversation_id: str) -> Optional[PrewarmedRoom]:
        """Pop a prewarmed room. Returns None if not available."""
        room = self._rooms.pop(conversation_id, None)
        if room:
            logger.info("Pre-warmed room consumed: %s", room.room_name)
        return room

    async def cleanup_stale(self, max_age_seconds: float = 60.0) -> None:
        """Periodic task to clean up rooms that were prewarmed but never used."""
        now = asyncio.get_event_loop().time()
        stale = [
            cid for cid, room in self._rooms.items()
            if (now - room.created_at) > max_age_seconds
        ]
        for cid in stale:
            room = self._rooms.pop(cid, None)
            if room:
                try:
                    room_api = lk_api.LiveKitAPI(
                        url=settings.livekit_url,
                        api_key=settings.livekit_api_key,
                        api_secret=settings.livekit_api_secret,
                    )
                    try:
                        await room_api.room.delete_room(
                            lk_api.DeleteRoomRequest(room=room.room_name)
                        )
                    finally:
                        await room_api.aclose()
                    logger.info("Cleaned stale pre-warmed room: %s", room.room_name)
                except Exception:
                    logger.warning("Failed to clean stale room: %s", room.room_name, exc_info=True)


# Module-level singleton
room_prewarmer = RoomPrewarmer()
