"""User account service: creation, lookup, authentication."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_extra
from app.core.security import dummy_verify, hash_password, verify_password
from app.db.enums import UserRole
from app.db.models import User
from app.schemas.auth import UserCreate

logger = get_logger(__name__)


class UserExistsError(Exception):
    pass


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.execute(
        select(User).where(func.lower(User.email) == email.lower())
    ).scalars().first()


def create_user(db: Session, payload: UserCreate) -> User:
    if get_user_by_email(db, str(payload.email)):
        raise UserExistsError(f"user {payload.email} already exists")
    user = User(
        email=str(payload.email).lower(),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    logger.info("user.created", extra=log_extra(user_id=str(user.id), role=user.role.value))
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    """Return the user on valid credentials, else ``None``.

    Always runs a password verification even when the user is missing so the
    response time does not reveal whether an account exists.
    """
    user = get_user_by_email(db, email)
    if user is None:
        dummy_verify(password)  # equalise timing so accounts cannot be enumerated
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    user.last_login_at = datetime.now(UTC)
    db.flush()
    return user


def count_owners(db: Session) -> int:
    return int(
        db.execute(
            select(func.count()).select_from(User).where(User.role == UserRole.OWNER)
        ).scalar_one()
    )
