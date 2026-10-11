"""Authentication endpoints: login, whoami, user administration."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_principal, rate_limit_login, require_owner
from app.core.config import settings
from app.core.logging import get_logger, log_extra
from app.core.security import Principal, create_access_token
from app.db.models import User
from app.schemas.auth import LoginRequest, MeResponse, TokenResponse, UserCreate, UserRead
from app.services import users as users_service
from app.services.audit import write_audit
from app.services.users import UserExistsError

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_login),
) -> TokenResponse:
    user = users_service.authenticate(db, str(payload.email), payload.password)
    if user is None:
        write_audit(
            db,
            actor=str(payload.email),
            actor_type="anonymous",
            action="login_failed",
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        db.commit()
        logger.warning("auth.login_failed", extra=log_extra(email=str(payload.email)))
        # Deliberately generic message (no account enumeration).
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    token = create_access_token(user.email, user.role, extra={"uid": str(user.id), "name": user.full_name})
    write_audit(
        db,
        actor=user.email,
        action="login_succeeded",
        entity_type="user",
        entity_id=str(user.id),
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        role=user.role,
        subject=user.email,
    )


@router.get("/me", response_model=MeResponse)
def me(principal: Principal = Depends(get_principal)) -> MeResponse:
    return MeResponse(subject=principal.subject, role=principal.role, auth_method=principal.auth_method)


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_owner),
) -> UserRead:
    try:
        user = users_service.create_user(db, payload)
    except UserExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    write_audit(
        db, actor=principal.subject, action="user_created",
        entity_type="user", entity_id=str(user.id), after={"email": user.email, "role": user.role.value},
    )
    db.commit()
    db.refresh(user)
    return user


@router.get("/users", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    _: Principal = Depends(require_owner),
) -> list[UserRead]:
    rows = db.execute(select(User).order_by(User.created_at)).scalars().all()
    return [UserRead.model_validate(u) for u in rows]
