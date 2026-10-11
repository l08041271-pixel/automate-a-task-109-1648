"""Security primitives: password hashing, JWT access tokens, API keys."""
from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings
from app.db.enums import UserRole

ALGORITHM = "HS256"

#: bcrypt ignores anything past 72 bytes, and modern releases raise instead of
#: truncating, so we truncate explicitly and deterministically.
_BCRYPT_MAX_BYTES = 72


def _prepare(plain: str) -> bytes:
    return plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
# bcrypt is used directly: passlib is unmaintained (last release 2020) and its
# bcrypt backend breaks against bcrypt >= 4.1.
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_prepare(plain), bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_prepare(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def dummy_verify(plain: str) -> None:
    """Burn roughly the same CPU time as a real check (anti user-enumeration)."""
    try:
        bcrypt.checkpw(
            _prepare(plain),
            bcrypt.hashpw(b"dummy-password", bcrypt.gensalt(rounds=settings.bcrypt_rounds)),
        )
    except ValueError:  # pragma: no cover
        pass


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

    Returns ``False`` when no admin key is configured so the API fails closed
    rather than silently allowing anonymous administrative access.
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
