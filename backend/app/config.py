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

    @property
    def supabase_user_endpoint(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1/user"


@lru_cache
def get_settings() -> Settings:
    return Settings()
