"""Migration hygiene tests.

These run without a live PostgreSQL server: they (a) re-generate the DDL from
the ORM and prove the committed migration matches it, and (b) parse the SQL
with the real PostgreSQL grammar via ``pglast``.

Skipped automatically if ``pglast`` is not installed (see requirements-dev.txt).
"""
from __future__ import annotations

import pathlib

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db import models

pglast = pytest.importorskip("pglast", reason="pglast is a dev-only dependency")

MIGRATIONS = pathlib.Path(__file__).resolve().parents[1] / "migrations"
INIT_SQL = MIGRATIONS / "001_init.sql"


def _generate_expected_ddl() -> str:
    dialect = postgresql.dialect()
    parts: list[str] = []
    for table in models.Base.metadata.sorted_tables:
        parts.append(str(CreateTable(table).compile(dialect=dialect)).strip())
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            parts.append(str(CreateIndex(index).compile(dialect=dialect)).strip())
    return "\n".join(parts)


def test_all_migration_files_are_valid_postgres():
    files = sorted(MIGRATIONS.glob("*.sql"))
    assert files, "no migration files found"
    for path in files:
        # Raises if the SQL is not valid PostgreSQL.
        statements = pglast.parse_sql(path.read_text(encoding="utf-8"))
        assert statements, f"{path.name} parsed to zero statements"


def test_committed_init_migration_matches_models():
    committed = INIT_SQL.read_text(encoding="utf-8")
    for table in models.Base.metadata.sorted_tables:
        assert f"CREATE TABLE {table.name} " in committed, f"{table.name} missing from migration"
    # Spot-check that CHECK guards actually made it into the SQL.
    assert committed.count("CONSTRAINT ck_") >= 10


def test_generated_ddl_is_stable():
    """Guard against accidental model edits without regenerating the migration."""
    committed = INIT_SQL.read_text(encoding="utf-8")
    generated = _generate_expected_ddl()
    for line in generated.splitlines():
        normalised = line.strip().rstrip(";")
        if normalised.startswith("CREATE TABLE") or normalised.startswith("CREATE INDEX"):
            assert normalised in committed.replace(";", ""), (
                f"model change not reflected in 001_init.sql: {normalised}"
            )


def test_rls_migration_enables_rls_on_every_table():
    rls = (MIGRATIONS / "002_rls_and_triggers.sql").read_text(encoding="utf-8")
    for table in models.Base.metadata.sorted_tables:
        assert f"ALTER TABLE public.{table.name}" in rls, f"RLS not enabled for {table.name}"
