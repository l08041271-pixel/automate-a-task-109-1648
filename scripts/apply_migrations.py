#!/usr/bin/env python
"""Apply the SQL migrations in ``migrations/`` in order.

Works against any PostgreSQL database, including Supabase.

    export DATABASE_URL="postgresql://postgres.<ref>:<pw>@...pooler.supabase.com:6543/postgres"
    python scripts/apply_migrations.py --dry-run     # list what would run
    python scripts/apply_migrations.py               # apply

Notes
-----
* Every migration is idempotent-ish: 001 uses CREATE TABLE (run once on an
  empty DB) and 002 uses CREATE OR REPLACE / IF EXISTS guards.
* Applied filenames are recorded in ``schema_migrations`` so re-running is safe.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402

MIGRATIONS_DIR = ROOT / "migrations"

TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    text PRIMARY KEY,
    checksum    text NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
);
"""


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply SQL migrations")
    parser.add_argument("--dry-run", action="store_true", help="list migrations without applying")
    args = parser.parse_args()

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print("no migration files found")
        return 1

    if args.dry_run:
        print("Would apply (in order):")
        for path in files:
            print(f"  {path.name}  ({_checksum(path.read_text())})")
        return 0

    if settings.is_sqlite:
        print("ERROR: DATABASE_URL points at SQLite. Set it to your PostgreSQL URL.")
        print("(For local dev, SQLite tables are created automatically at startup.)")
        return 2

    try:
        import psycopg
    except ImportError:  # pragma: no cover
        print("ERROR: psycopg is not installed. Run: pip install 'psycopg[binary]'")
        return 2

    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(TRACKING_DDL)
            cur.execute("SELECT filename, checksum FROM schema_migrations")
            applied = {row[0]: row[1] for row in cur.fetchall()}

        for path in files:
            text = path.read_text(encoding="utf-8")
            sum_ = _checksum(text)
            if path.name in applied:
                if applied[path.name] != sum_:
                    print(f"WARNING: {path.name} was applied but has since changed (checksum drift)")
                else:
                    print(f"skip  {path.name} (already applied)")
                continue
            print(f"apply {path.name} ...")
            with conn.cursor() as cur:
                cur.execute(text)
                cur.execute(
                    "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
                    (path.name, sum_),
                )
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
