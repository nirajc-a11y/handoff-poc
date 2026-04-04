"""Request correlation ID middleware.

Generates a unique ID per request and stores it in a context variable
so all log output within the request includes the correlation ID.
"""

import logging
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Use incoming header or generate new
        corr_id = request.headers.get("X-Request-Id", str(uuid.uuid4())[:8])
        correlation_id_var.set(corr_id)

        response: Response = await call_next(request)
        response.headers["X-Request-Id"] = corr_id
        return response


class CorrelationIdFilter(logging.Filter):
    """Logging filter that adds correlation_id to all log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get("")
        return True
