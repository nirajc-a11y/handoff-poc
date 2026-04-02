from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def get_tenant_id(
    x_tenant_id: UUID = Header(..., description="Tenant ID"),
) -> UUID:
    return x_tenant_id


async def get_current_user_id(
    x_user_id: UUID = Header(..., description="User ID"),
) -> UUID:
    return x_user_id


class TenantContext:
    def __init__(self, tenant_id: UUID, user_id: UUID, db: AsyncSession):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.db = db


async def get_tenant_context(
    tenant_id: UUID = Depends(get_tenant_id),
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    return TenantContext(tenant_id=tenant_id, user_id=user_id, db=db)
