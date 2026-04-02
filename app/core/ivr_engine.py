"""IVR menu traversal and DTMF handling engine."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.ivr_menu import IVRMenu, IVRMenuOption

logger = logging.getLogger(__name__)


@dataclass
class IVRAction:
    action_type: str  # "submenu", "ai_handoff", "human_queue", "play_message", "hangup"
    target_id: UUID | None = None  # submenu ID
    target_config: dict | None = field(default_factory=dict)  # queue_name, skill_requirements
    message: str | None = None  # text to play


class IVREngine:
    """Resolves IVR menu trees and translates DTMF digits into routing actions."""

    async def get_menu_prompt(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        menu_id: UUID | None = None,
    ) -> tuple[str, UUID]:
        """Return the welcome message and menu ID for a given (or root) IVR menu.

        If *menu_id* is ``None`` the root menu for the tenant is resolved
        automatically.  The returned string includes appended option labels
        (e.g. ``"Press 1 for Sales, Press 2 for Support"``).
        """
        if menu_id is None:
            stmt = (
                select(IVRMenu)
                .where(
                    IVRMenu.tenant_id == tenant_id,
                    IVRMenu.is_root.is_(True),
                    IVRMenu.is_deleted.is_(False),
                )
                .options(selectinload(IVRMenu.options))
                .limit(1)
            )
        else:
            stmt = (
                select(IVRMenu)
                .where(
                    IVRMenu.id == menu_id,
                    IVRMenu.tenant_id == tenant_id,
                    IVRMenu.is_deleted.is_(False),
                )
                .options(selectinload(IVRMenu.options))
            )

        result = await db.execute(stmt)
        menu = result.scalar_one_or_none()

        if menu is None:
            raise ValueError(
                f"IVR menu not found (tenant_id={tenant_id}, menu_id={menu_id})"
            )

        # Build the prompt text
        prompt_parts: list[str] = []
        if menu.welcome_message:
            prompt_parts.append(menu.welcome_message)

        option_lines: list[str] = []
        for option in menu.options:
            label = option.label or option.action_type
            option_lines.append(f"Press {option.digit} for {label}")

        if option_lines:
            prompt_parts.append(". ".join(option_lines) + ".")

        prompt = " ".join(prompt_parts) if prompt_parts else "Welcome. Please select an option."

        return prompt, menu.id

    async def process_dtmf(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        menu_id: UUID,
        digit: str,
    ) -> IVRAction:
        """Look up the IVR option for *digit* under *menu_id* and return the corresponding action."""
        stmt = select(IVRMenuOption).where(
            IVRMenuOption.menu_id == menu_id,
            IVRMenuOption.tenant_id == tenant_id,
            IVRMenuOption.digit == digit,
        )

        result = await db.execute(stmt)
        option = result.scalar_one_or_none()

        if option is None:
            logger.info(
                "Invalid DTMF digit %r for menu %s (tenant %s)",
                digit,
                menu_id,
                tenant_id,
            )
            return IVRAction(
                action_type="play_message",
                message="Invalid option, please try again.",
            )

        return IVRAction(
            action_type=option.action_type,
            target_id=option.target_id,
            target_config=option.target_config or {},
            message=option.label,
        )


# Module-level singleton
ivr_engine = IVREngine()
