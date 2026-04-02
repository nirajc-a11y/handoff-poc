"""Shared utilities for mock providers."""

from __future__ import annotations

import asyncio
import random
from uuid import uuid4


def generate_mock_id(prefix: str) -> str:
    """Return a deterministic-looking mock identifier: ``{prefix}-{hex12}``."""
    return f"{prefix}-{uuid4().hex[:12]}"


async def random_delay(min_s: float, max_s: float) -> None:
    """Sleep for a uniformly random duration between *min_s* and *max_s* seconds."""
    await asyncio.sleep(random.uniform(min_s, max_s))
