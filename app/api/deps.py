"""FastAPI dependencies: DB session, authentication, authorisation, limits."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status

from app.core import security
from app.core.config import settings
from app.core.rate_limit import FixedWindowLimiter
from app.core.security import Principal, TokenError
from app.db.enums import UserRole
from app.db.session import get_db

# Shared limiter instances (process-wide).
general_limiter = FixedWindowLimiter(settings.rate_limit_per_minute)
webhook_limiter = FixedWindowLimiter(settings.rate_limit_webhook_per_minute)
# Brute-force protection for the login endpoint (stricter, per client).
login_limiter = FixedWindowLimiter(10)


def client_key(request: Request) -> str:
    """Best-effort client identity for rate limiting.

    Only trusts proxy headers when explicitly running behind one; falls back
    to the socket peer address.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request) -> None:
    result = general_limiter.check(client_key(request))
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please slow down.",
            headers={"Retry-After": str(result.retry_after)},
        )


def rate_limit_login(request: Request) -> None:
    """Stricter limit for credential endpoints (brute-force mitigation)."""
    result = login_limiter.check(client_key(request))
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(result.retry_after)},
        )


def get_principal(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> Principal:
    """Authenticate via ``X-API-Key`` (service) or ``Authorization: Bearer``."""
    if security.api_key_is_valid(x_api_key):
        return Principal(subject="service:admin", role=UserRole.OWNER, auth_method="api_key")

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            claims = security.decode_access_token(token)
        except TokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        try:
            role = UserRole(claims.get("role", "VIEWER"))
        except ValueError:
            role = UserRole.VIEWER
        return Principal(subject=str(claims.get("sub", "unknown")), role=role, auth_method="jwt")

    detail = "Authentication required."
    if not settings.admin_api_key:
        detail = (
            "Authentication is not configured on this server (ADMIN_API_KEY is "
            "empty). Set it in the environment before using protected endpoints."
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_writer(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.can_write():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role cannot modify records.",
        )
    return principal


def require_owner(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner role required for this action.",
        )
    return principal


__all__ = [
    "get_db",
    "get_principal",
    "require_writer",
    "require_owner",
    "rate_limit",
    "rate_limit_login",
    "client_key",
]
