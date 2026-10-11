"""Application configuration.

All values come from environment variables (see `.env.example`).
Secrets are never hardcoded; missing-but-required secrets fail loudly in
production and fall back to safe, clearly-labelled dev defaults otherwise.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


def _normalise_db_url(url: str) -> str:
    """Make raw Supabase/Heroku-style URLs work with SQLAlchemy 2.x.

    ``postgres://`` and bare ``postgresql://`` are rewritten to the psycopg3
    driver form so a copy-pasted Supabase connection string "just works".
    """
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---------------------------------------------------------------
    app_name: str = "MassageVIP Riyadh Growth API"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    log_level: str = "INFO"
    api_v1_prefix: str = "/api"
    public_base_url: str = "http://127.0.0.1:8000"

    # --- Database ----------------------------------------------------------
    database_url: str = "sqlite:///./massagevip_dev.db"

    # --- Security ----------------------------------------------------------
    secret_key: str = "CHANGE_ME_dev_only_insecure_secret"
    admin_api_key: str = ""
    access_token_expire_minutes: int = 60
    # bcrypt work factor. 12 in production; tests lower it to stay fast.
    bcrypt_rounds: int = 12
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    # --- Rate limiting -----------------------------------------------------
    rate_limit_per_minute: int = 60
    rate_limit_webhook_per_minute: int = 120

    # --- WhatsApp ----------------------------------------------------------
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = "v21.0"
    whatsapp_graph_base: str = "https://graph.facebook.com"
    whatsapp_dry_run: bool = True

    # --- Business rules ----------------------------------------------------
    business_city: str = "Riyadh"
    business_timezone: str = "Asia/Riyadh"
    business_country_code: str = "+966"
    hot_service_keywords: str = (
        "massage,spa,home service,booking,appointment"
    )

    # ------------------------------------------------------------------ #
    # Validators
    # ------------------------------------------------------------------ #
    @field_validator("database_url")
    @classmethod
    def _validate_db_url(cls, v: str) -> str:
        return _normalise_db_url(v)

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid LOG_LEVEL: {v}")
        return v

    # ------------------------------------------------------------------ #
    # Derived helpers
    # ------------------------------------------------------------------ #
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def hot_service_keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in self.hot_service_keywords.split(",") if k.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def assert_production_ready(self) -> None:
        """Fail fast on insecure production configuration."""
        if not self.is_production:
            return
        problems: list[str] = []
        if self.secret_key.startswith("CHANGE_ME") or len(self.secret_key) < 32:
            problems.append("SECRET_KEY is missing/short/placeholder")
        if not self.admin_api_key or self.admin_api_key.startswith("CHANGE_ME"):
            problems.append("ADMIN_API_KEY is missing/placeholder")
        if self.is_sqlite:
            problems.append("DATABASE_URL still points at SQLite (use Supabase Postgres)")
        if problems:
            raise RuntimeError(
                "Refusing to start in production with insecure config: "
                + "; ".join(problems)
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
