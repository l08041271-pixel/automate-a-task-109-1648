"""Structured JSON logging with request/job correlation IDs.

We never log full phone numbers, tokens or message bodies at INFO level.
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings

# Correlation IDs propagated through a request / background run.
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
run_id_ctx: ContextVar[str | None] = ContextVar("run_id", default=None)

_SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "admin_api_key",
    "access_token",
    "secret",
    "secret_key",
    "password",
    "phone",
    "phone_number",
    "wa_id",
    "token",
}


def _redact(value: Any) -> Any:
    if isinstance(value, str) and len(value) > 6:
        return value[:2] + "***" + value[-2:]
    return "***"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_ctx.get()
        if rid:
            payload["request_id"] = rid
        runid = run_id_ctx.get()
        if runid:
            payload["run_id"] = runid

        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            for k, v in extra.items():
                payload[k] = _redact(v) if k.lower() in _SENSITIVE_KEYS else v

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    # Idempotent: avoid duplicate handlers on reload.
    if getattr(root, "_massagevip_configured", False):
        return
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    if settings.environment == "development":
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s :: %(message)s")
        )
    else:
        handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(settings.log_level)
    # Silence noisy libraries.
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine"):
        logging.getLogger(noisy).setLevel("WARNING")
    root._massagevip_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_extra(**fields: Any) -> dict[str, Any]:
    """Convenience: ``logger.info("m", extra=log_extra(lead_id=1))``."""
    return {"extra_fields": fields}
