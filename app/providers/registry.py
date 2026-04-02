"""Provider registry — resolves channel providers per tenant."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.base import (
    EmailProvider,
    SMSProvider,
    TelephonyProvider,
    WhatsAppProvider,
)

logger = logging.getLogger(__name__)

# Channel name constants
CHANNEL_TELEPHONY = "telephony"
CHANNEL_WHATSAPP = "whatsapp"
CHANNEL_EMAIL = "email"
CHANNEL_SMS = "sms"

_MOCK = "mock"


class ProviderRegistry:
    """Central registry mapping (channel, provider_name) -> provider instance.

    On construction the registry lazily creates mock providers for every
    channel so that local development works without any external services.
    """

    def __init__(self) -> None:
        # channel -> provider_name -> instance
        self._providers: dict[str, dict[str, Any]] = {
            CHANNEL_TELEPHONY: {},
            CHANNEL_WHATSAPP: {},
            CHANNEL_EMAIL: {},
            CHANNEL_SMS: {},
        }
        self._mocks_initialised = False

    # ------------------------------------------------------------------
    # Lazy mock initialisation (avoids circular imports at module load)
    # ------------------------------------------------------------------

    def _ensure_mocks(self) -> None:
        if self._mocks_initialised:
            return
        from app.providers.mock.email import MockEmailProvider
        from app.providers.mock.sms import MockSMSProvider
        from app.providers.mock.telephony import MockTelephonyProvider
        from app.providers.mock.whatsapp import MockWhatsAppProvider

        self._providers[CHANNEL_TELEPHONY].setdefault(_MOCK, MockTelephonyProvider())
        self._providers[CHANNEL_WHATSAPP].setdefault(_MOCK, MockWhatsAppProvider())
        self._providers[CHANNEL_EMAIL].setdefault(_MOCK, MockEmailProvider())
        self._providers[CHANNEL_SMS].setdefault(_MOCK, MockSMSProvider())
        self._mocks_initialised = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, channel: str, name: str, provider: Any) -> None:
        """Register a provider instance under *channel* / *name*."""
        if channel not in self._providers:
            self._providers[channel] = {}
        self._providers[channel][name] = provider
        logger.info("Registered %s provider '%s'", channel, name)

    # ------------------------------------------------------------------
    # Per-channel accessors
    # ------------------------------------------------------------------

    async def _resolve(
        self, channel: str, tenant_id: UUID, db: AsyncSession
    ) -> Any:
        """Look up the tenant's preferred provider for *channel*.

        Falls back to ``"mock"`` when no preference is configured or the
        configured provider has not been registered.
        """
        self._ensure_mocks()

        provider_name = await self._tenant_provider_name(channel, tenant_id, db)
        providers = self._providers.get(channel, {})
        provider = providers.get(provider_name)
        if provider is None:
            logger.warning(
                "Provider '%s' not found for channel '%s', tenant %s — falling back to mock",
                provider_name,
                channel,
                tenant_id,
            )
            provider = providers.get(_MOCK)
        return provider

    async def get_telephony(
        self, tenant_id: UUID, db: AsyncSession
    ) -> TelephonyProvider:
        return await self._resolve(CHANNEL_TELEPHONY, tenant_id, db)

    async def get_whatsapp(
        self, tenant_id: UUID, db: AsyncSession
    ) -> WhatsAppProvider:
        return await self._resolve(CHANNEL_WHATSAPP, tenant_id, db)

    async def get_email(
        self, tenant_id: UUID, db: AsyncSession
    ) -> EmailProvider:
        return await self._resolve(CHANNEL_EMAIL, tenant_id, db)

    async def get_sms(
        self, tenant_id: UUID, db: AsyncSession
    ) -> SMSProvider:
        return await self._resolve(CHANNEL_SMS, tenant_id, db)

    # ------------------------------------------------------------------
    # Tenant config lookup
    # ------------------------------------------------------------------

    @staticmethod
    async def _tenant_provider_name(
        channel: str, tenant_id: UUID, db: AsyncSession
    ) -> str:
        """Read the tenant's ``config`` JSONB to find the provider name.

        Expected shape:  ``{"providers": {"telephony": "twilio", ...}}``
        Returns ``"mock"`` when the key is absent.
        """
        try:
            from app.db.models.tenant import Tenant

            result = await db.execute(
                select(Tenant.config).where(Tenant.id == tenant_id)
            )
            config = result.scalar_one_or_none()
            if config and isinstance(config, dict):
                return config.get("providers", {}).get(channel, _MOCK)
        except Exception:
            logger.debug(
                "Could not read tenant config for %s — defaulting to mock",
                tenant_id,
                exc_info=True,
            )
        return _MOCK


# Module-level singleton
provider_registry = ProviderRegistry()
