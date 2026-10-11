#!/usr/bin/env python
"""Create (or promote) the first owner account.

    python scripts/create_owner.py --email owner@massagevip.sa --name "Owner"
    # password is prompted for (never passed on the command line / shell history)

Safe to run against production: it only inserts a user row.
"""
from __future__ import annotations

import argparse
import getpass
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.db.enums import UserRole
from app.db.session import SessionLocal, init_db
from app.schemas.auth import UserCreate
from app.services import users as users_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the first owner account")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--password-stdin", action="store_true",
                        help="read the password from stdin instead of prompting")
    args = parser.parse_args()

    if args.password_stdin:
        password = sys.stdin.readline().strip()
    else:
        password = getpass.getpass("New owner password (min 10 chars): ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("ERROR: passwords do not match")
            return 1

    if len(password) < 10:
        print("ERROR: password must be at least 10 characters")
        return 1

    if settings.is_sqlite:
        init_db()  # dev convenience

    with SessionLocal() as db:
        existing = users_service.get_user_by_email(db, args.email)
        if existing:
            existing.role = UserRole.OWNER
            existing.is_active = True
            db.commit()
            print(f"promoted existing user {args.email} to OWNER")
            return 0
        user = users_service.create_user(
            db,
            UserCreate(email=args.email, password=password, full_name=args.name, role=UserRole.OWNER),
        )
        db.commit()
        print(f"created OWNER {user.email} ({user.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
