"""Security primitives: API-key auth, JWT access tokens, password hashing."""
from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.db.enums import UserRole

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed)
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def create_access_token(
    subject: str,
    role: UserRole,
    *,
    expires_minutes: int | None = None,
    extra: dict | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    payload = {
        "sub": subject,
        "role": role.value,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": uuid.uuid4().hex,
        **(extra or {}),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


class TokenError(Exception):
    pass


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid token") from exc


# --------------------------------------------------------------------------- #
# API keys
# --------------------------------------------------------------------------- #
def api_key_is_valid(candidate: str | None) -> bool:
    """Constant-time comparison against the configured admin key.

    Returns ``False`` when no admin key is configured so the API fails
    closed instead of silently allowing anonymous admin access.
    """
    configured = settings.admin_api_key
    if not configured or not candidate:
        return False
    return hmac.compare_digest(candidate.encode(), configured.encode())


@dataclass(frozen=True)
class Principal:
    """The authenticated caller."""

    subject: str
    role: UserRole
    auth_method: str  # "api_key" | "jwt"

    @property
    def is_owner(self) -> bool:
        return self.role == UserRole.OWNER

    def can_write(self) -> bool:
        return self.role in (UserRole.OWNER, UserRole.STAFF)
