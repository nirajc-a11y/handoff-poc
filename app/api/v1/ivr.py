"""IVR menu management endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.ivr_menu import IVRMenu, IVRMenuOption
from app.dependencies import get_db, get_tenant_id

router = APIRouter(prefix="/ivr", tags=["ivr"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class IVRMenuCreate(BaseModel):
    name: str
    is_root: bool | None = None
    welcome_message: str | None = None
    config: dict | None = None


class IVRMenuUpdate(BaseModel):
    name: str | None = None
    is_root: bool | None = None
    welcome_message: str | None = None
    config: dict | None = None


class IVRMenuOptionCreate(BaseModel):
    digit: str
    label: str | None = None
    action_type: str  # submenu, ai_handoff, human_queue, play_message, hangup
    target_id: UUID | None = None
    target_config: dict | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _option_dict(opt: IVRMenuOption) -> dict:
    return {
        "id": str(opt.id),
        "menu_id": str(opt.menu_id),
        "digit": opt.digit,
        "label": opt.label,
        "action_type": opt.action_type,
        "target_id": str(opt.target_id) if opt.target_id else None,
        "target_config": opt.target_config,
        "sort_order": opt.sort_order,
        "created_at": opt.created_at.isoformat() if opt.created_at else None,
    }


def _menu_dict(menu: IVRMenu, include_options: bool = False) -> dict:
    d: dict = {
        "id": str(menu.id),
        "tenant_id": str(menu.tenant_id),
        "name": menu.name,
        "is_root": menu.is_root,
        "welcome_message": menu.welcome_message,
        "config": menu.config,
        "created_at": menu.created_at.isoformat() if menu.created_at else None,
        "updated_at": menu.updated_at.isoformat() if menu.updated_at else None,
    }
    if include_options:
        d["options"] = [_option_dict(o) for o in menu.options]
    return d


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/menus")
async def list_menus(
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    stmt = (
        select(IVRMenu)
        .where(
            IVRMenu.tenant_id == tenant_id,
            IVRMenu.is_deleted == False,  # noqa: E712
        )
        .order_by(IVRMenu.created_at.desc())
    )
    result = await db.execute(stmt)
    menus = result.scalars().all()
    return [_menu_dict(m) for m in menus]


@router.post("/menus")
async def create_menu(
    body: IVRMenuCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    menu = IVRMenu(
        tenant_id=tenant_id,
        name=body.name,
        is_root=body.is_root if body.is_root is not None else False,
        welcome_message=body.welcome_message,
        config=body.config or {},
    )
    db.add(menu)
    await db.commit()
    await db.refresh(menu)
    return _menu_dict(menu)


@router.get("/menus/{menu_id}")
async def get_menu(
    menu_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    stmt = (
        select(IVRMenu)
        .where(
            IVRMenu.id == menu_id,
            IVRMenu.tenant_id == tenant_id,
            IVRMenu.is_deleted == False,  # noqa: E712
        )
        .options(selectinload(IVRMenu.options))
    )
    result = await db.execute(stmt)
    menu = result.scalar_one_or_none()
    if menu is None:
        raise HTTPException(status_code=404, detail="IVR menu not found")
    return _menu_dict(menu, include_options=True)


@router.patch("/menus/{menu_id}")
async def update_menu(
    menu_id: UUID,
    body: IVRMenuUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    stmt = select(IVRMenu).where(
        IVRMenu.id == menu_id,
        IVRMenu.tenant_id == tenant_id,
        IVRMenu.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    menu = result.scalar_one_or_none()
    if menu is None:
        raise HTTPException(status_code=404, detail="IVR menu not found")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    for key, value in updates.items():
        setattr(menu, key, value)

    await db.commit()
    await db.refresh(menu)
    return _menu_dict(menu)


@router.post("/menus/{menu_id}/options")
async def create_menu_option(
    menu_id: UUID,
    body: IVRMenuOptionCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    # Verify menu exists
    stmt = select(IVRMenu).where(
        IVRMenu.id == menu_id,
        IVRMenu.tenant_id == tenant_id,
        IVRMenu.is_deleted == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    menu = result.scalar_one_or_none()
    if menu is None:
        raise HTTPException(status_code=404, detail="IVR menu not found")

    option = IVRMenuOption(
        tenant_id=tenant_id,
        menu_id=menu_id,
        digit=body.digit,
        label=body.label,
        action_type=body.action_type,
        target_id=body.target_id,
        target_config=body.target_config or {},
    )
    db.add(option)
    await db.commit()
    await db.refresh(option)
    return _option_dict(option)
