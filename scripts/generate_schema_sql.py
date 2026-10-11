#!/usr/bin/env python
"""Regenerate ``migrations/001_init.sql`` from the SQLAlchemy models.

Keeping the migration generated (and reviewed) guarantees the PostgreSQL
schema can never silently drift from the ORM definitions.

Usage:
    python scripts/generate_schema_sql.py [output_path]
"""
from __future__ import annotations

import pathlib
import sys

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import models  # noqa: E402

HEADER = """\
-- ===========================================================================
-- MassageVIP Riyadh — initial PostgreSQL schema (Supabase compatible)
-- ---------------------------------------------------------------------------
-- GENERATED FILE — do not edit by hand.
-- Regenerate with:  python scripts/generate_schema_sql.py
-- Source of truth:  app/db/models/*.py
--
-- Apply in the Supabase SQL editor, or with:
--   psql "$DATABASE_URL" -f migrations/001_init.sql
-- ===========================================================================

BEGIN;
"""

FOOTER = "\nCOMMIT;\n"


def main() -> None:
    out_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "migrations" / "001_init.sql"
    dialect = postgresql.dialect()
    chunks: list[str] = [HEADER]
    for table in models.Base.metadata.sorted_tables:
        chunks.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";\n")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            chunks.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";\n")
        chunks.append("\n")
    chunks.append(FOOTER)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(chunks), encoding="utf-8")
    print(f"wrote {out_path} ({len(models.Base.metadata.sorted_tables)} tables)")


if __name__ == "__main__":
    main()
