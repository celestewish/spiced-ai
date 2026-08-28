"""Environment-based configuration, loaded from process env or a local .env file."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    database_url: str = ""

    # Billing Foundation (Market-Viability Roadmap, Phase 5). Test/sandbox
    # Stripe keys only in every environment this app ships to today --
    # flipping to a live secret key and live Price ids is a config change,
    # not a code change, when that day comes. stripe_price_id_* are the
    # Price objects (not Product objects) for the paid tiers configured in
    # the developer's own Stripe dashboard; "free" has no Stripe price at
    # all, since it's never checked out.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id_indie: str = ""
    stripe_price_id_studio: str = ""

    @property
    def supabase_user_endpoint(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1/user"


@lru_cache
def get_settings() -> Settings:
    return Settings()
