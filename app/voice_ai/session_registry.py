"""Registry of active VoiceAI sessions for supervisor listen/whisper/barge.

Module-level singleton mapping conversation_id -> SessionHandle.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class SessionHandle:
    """Everything a supervisor needs to interact with an active call."""

    session: object  # VoiceAISession (avoid circular import)
    plivo_ws: WebSocket  # The Plivo bidirectional stream WebSocket
    stream_sid: str = ""
    listeners: set[asyncio.Queue] = field(default_factory=set)

    async def forward_to_listeners(self, audio_bytes: bytes, source: str):
        """Send audio to all supervisor listener queues.

        Args:
            audio_bytes: Raw mulaw audio chunk.
            source: 'caller' or 'ai' — so the frontend can mix/label.
        """
        dead: list[asyncio.Queue] = []
        for q in list(self.listeners):
            try:
                q.put_nowait({"source": source, "audio": audio_bytes})
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.listeners.discard(q)


# Module-level registry
_sessions: dict[str, SessionHandle] = {}


def register(conv_id: str, handle: SessionHandle) -> None:
    _sessions[conv_id] = handle
    logger.info("Session registered: conv=%s (active=%d)", conv_id, len(_sessions))


def unregister(conv_id: str) -> None:
    _sessions.pop(conv_id, None)
    logger.info("Session unregistered: conv=%s (active=%d)", conv_id, len(_sessions))


def get(conv_id: str) -> SessionHandle | None:
    return _sessions.get(conv_id)


def list_active() -> list[str]:
    return list(_sessions.keys())
