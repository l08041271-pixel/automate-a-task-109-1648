#!/usr/bin/env python
"""Create a local ``.env`` from ``.env.example`` with freshly generated secrets.

Never prints or commits the generated secrets.

    python scripts/generate_env.py            # writes .env (refuses to overwrite)
    python scripts/generate_env.py --force    # overwrite an existing .env
"""
from __future__ import annotations

import argparse
import pathlib
import secrets
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.example"
TARGET = ROOT / ".env"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="overwrite existing .env")
    args = parser.parse_args()

    if not EXAMPLE.exists():
        print(f"ERROR: {EXAMPLE} not found")
        return 1
    if TARGET.exists() and not args.force:
        print(f"ERROR: {TARGET} already exists (use --force to overwrite)")
        return 1

    secret_key = secrets.token_urlsafe(48)
    admin_key = secrets.token_urlsafe(48)
    verify_token = secrets.token_urlsafe(24)

    text = EXAMPLE.read_text(encoding="utf-8")
    text = text.replace(
        'SECRET_KEY="CHANGE_ME_generate_with_secrets_token_urlsafe"',
        f'SECRET_KEY="{secret_key}"',
    )
    text = text.replace(
        'ADMIN_API_KEY="CHANGE_ME_generate_with_secrets_token_urlsafe"',
        f'ADMIN_API_KEY="{admin_key}"',
    )
    text = text.replace(
        'WHATSAPP_VERIFY_TOKEN="CHANGE_ME_webhook_verify_token"',
        f'WHATSAPP_VERIFY_TOKEN="{verify_token}"',
    )
    TARGET.write_text(text, encoding="utf-8")
    TARGET.chmod(0o600)
    print(f"wrote {TARGET} (mode 600) with generated SECRET_KEY / ADMIN_API_KEY")
    print("Show the admin key when you need it:  grep ADMIN_API_KEY .env")
    return 0


if __name__ == "__main__":
    sys.exit(main())
