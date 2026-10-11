"""Authentication / authorisation tests (Phase 3)."""
from __future__ import annotations

import pytest

from app.db.enums import UserRole
from app.db.session import SessionLocal
from app.schemas.auth import UserCreate
from app.services import users as users_service

OWNER = {"email": "owner@massagevip.sa", "password": "super-secret-pass", "role": UserRole.OWNER}
STAFF = {"email": "staff@massagevip.sa", "password": "staff-secret-pass", "role": UserRole.STAFF}


@pytest.fixture
def owner_user():
    with SessionLocal() as db:
        user = users_service.create_user(db, UserCreate(**OWNER))
        db.commit()
        return {"email": user.email, "id": str(user.id)}


@pytest.fixture
def staff_user():
    with SessionLocal() as db:
        user = users_service.create_user(db, UserCreate(**STAFF))
        db.commit()
        return {"email": user.email, "id": str(user.id)}


def _login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_login_succeeds_and_token_works(client, owner_user):
    resp = _login(client, OWNER["email"], OWNER["password"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "OWNER"

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["subject"] == OWNER["email"]
    assert me.json()["auth_method"] == "jwt"


def test_login_with_wrong_password_is_401(client, owner_user):
    assert _login(client, OWNER["email"], "wrong-password-1").status_code == 401


def test_login_with_unknown_email_is_401(client):
    assert _login(client, "nobody@massagevip.sa", "whatever-pass-1").status_code == 401


def test_login_response_does_not_leak_existence(client, owner_user):
    unknown = _login(client, "nobody@massagevip.sa", "whatever-pass-1")
    wrong_pw = _login(client, OWNER["email"], "wrong-password-1")
    assert unknown.json()["detail"] == wrong_pw.json()["detail"]


def test_login_is_rate_limited(client, owner_user):
    for _ in range(10):
        _login(client, OWNER["email"], "wrong-password-1")
    resp = _login(client, OWNER["email"], OWNER["password"])
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


def test_staff_token_cannot_create_users(client, staff_user):
    token = _login(client, STAFF["email"], STAFF["password"]).json()["access_token"]
    resp = client.post(
        "/api/auth/users",
        json={"email": "x@massagevip.sa", "password": "another-secret-1", "role": "STAFF"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_owner_can_create_user_and_duplicate_is_409(client, owner_user):
    token = _login(client, OWNER["email"], OWNER["password"]).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"email": "new@massagevip.sa", "password": "brand-new-secret", "role": "STAFF"}

    first = client.post("/api/auth/users", json=payload, headers=headers)
    assert first.status_code == 201
    assert first.json()["email"] == "new@massagevip.sa"
    assert "hashed_password" not in first.json()

    assert client.post("/api/auth/users", json=payload, headers=headers).status_code == 409


def test_password_is_never_returned_or_stored_in_plaintext(client, owner_user):
    with SessionLocal() as db:
        user = users_service.get_user_by_email(db, OWNER["email"])
        assert user.hashed_password != OWNER["password"]
        assert user.hashed_password.startswith("$2")  # bcrypt


def test_audit_log_records_login_attempts(client, owner_user):
    from sqlalchemy import select

    from app.db.models import AuditLog

    _login(client, OWNER["email"], OWNER["password"])
    _login(client, OWNER["email"], "wrong-password-1")
    with SessionLocal() as db:
        actions = db.execute(select(AuditLog.action)).scalars().all()
    assert "login_succeeded" in actions
    assert "login_failed" in actions
