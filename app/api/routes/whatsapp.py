"""WhatsApp Cloud API webhook.

GET  /api/webhooks/whatsapp  — Meta's verification handshake
POST /api/webhooks/whatsapp  — inbound messages / delivery statuses

Security: every POST is validated against the ``X-Hub-Signature-256`` HMAC
computed with your WhatsApp app secret. If no secret is configured the
endpoint returns 503 rather than trusting unauthenticated input.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import client_key, get_db, webhook_limiter
from app.core.config import settings
from app.core.logging import get_logger, log_extra
from app.services import conversations as conversations_service
from app.services import whatsapp as wa

router = APIRouter(prefix="/webhooks", tags=["whatsapp"])
logger = get_logger(__name__)


@router.get("/whatsapp", response_class=PlainTextResponse)
def verify_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
) -> PlainTextResponse:
    """Meta calls this once when you register the webhook URL."""
    if not settings.whatsapp_verify_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp webhook is not configured (WHATSAPP_VERIFY_TOKEN unset).",
        )
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("whatsapp.webhook_verified")
        return PlainTextResponse(content=hub_challenge or "", status_code=200)
    logger.warning("whatsapp.webhook_verification_failed")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed")


@router.post("/whatsapp")
async def receive_webhook(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    # --- rate limit -------------------------------------------------------
    limit = webhook_limiter.check(client_key(request))
    if not limit.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many webhook calls",
            headers={"Retry-After": str(limit.retry_after)},
        )

    # --- signature --------------------------------------------------------
    if not settings.whatsapp_app_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp app secret is not configured; refusing unverified input.",
        )
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not wa.verify_signature(raw_body, signature):
        logger.warning("whatsapp.bad_signature")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    payload = await request.json()
    if payload.get("object") != "whatsapp_business_account":
        # Not an event we handle; acknowledge so Meta stops retrying.
        return {"status": "ignored"}

    messages, statuses = wa.parse_webhook(payload)
    processed = 0
    duplicates = 0
    errors = 0

    for msg in messages:
        try:
            result = conversations_service.ingest_inbound(db, msg)
        except Exception as exc:  # noqa: BLE001 - never fail the whole batch
            db.rollback()
            errors += 1
            logger.exception("whatsapp.ingest_failed: %s", exc)
            continue
        if result is None:
            duplicates += 1
            continue
        processed += 1
        db.commit()

    if statuses:
        _record_statuses(statuses)

    logger.info(
        "whatsapp.webhook_processed",
        extra=log_extra(processed=processed, duplicates=duplicates, errors=errors),
    )
    response.status_code = status.HTTP_200_OK
    return {"status": "received", "processed": processed, "duplicates": duplicates}


def _record_statuses(statuses: list[dict]) -> None:
    """Log delivery statuses. Message status updates are a later enhancement."""
    for entry in statuses:
        logger.info(
            "whatsapp.status",
            extra=log_extra(
                message_id=entry.get("id"), status=entry.get("status")
            ),
        )
