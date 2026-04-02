"""Aggregate all v1 routers."""

from fastapi import APIRouter

from app.api.v1.agents import router as agents_router
from app.api.v1.calls import router as calls_router
from app.api.v1.campaigns import router as campaigns_router
from app.api.v1.channels.email import router as email_router
from app.api.v1.channels.sms import router as sms_router
from app.api.v1.channels.whatsapp import router as whatsapp_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.handoffs import router as handoffs_router
from app.api.v1.ivr import router as ivr_router
from app.api.v1.leads import router as leads_router
from app.api.v1.tenants import router as tenants_router
from app.api.v1.plivo import router as plivo_router
from app.api.v1.plivo_stream import router as plivo_stream_router
from app.api.v1.twilio import router as twilio_router
from app.api.v1.webhooks import router as webhooks_router
from app.api.v1.ws import router as ws_router

v1_router = APIRouter()

v1_router.include_router(tenants_router)
v1_router.include_router(campaigns_router)
v1_router.include_router(leads_router)
v1_router.include_router(ivr_router)
v1_router.include_router(calls_router)
v1_router.include_router(conversations_router)
v1_router.include_router(handoffs_router)
v1_router.include_router(agents_router)
v1_router.include_router(whatsapp_router)
v1_router.include_router(email_router)
v1_router.include_router(sms_router)
v1_router.include_router(plivo_router)
v1_router.include_router(plivo_stream_router)
v1_router.include_router(twilio_router)
v1_router.include_router(webhooks_router)
v1_router.include_router(ws_router)
