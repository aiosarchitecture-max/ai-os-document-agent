from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI_OS Core"
    version: str = "v3.0.0-foundation"
    environment: str = "development"
    database_url: str = "sqlite:///./aios.db"
    api_token: str = ""
    approval_signing_key: str = ""
    apps_script_webapp_url: str = ""
    apps_script_secret: str = ""
    ai_os_root_folder_id: str = ""
    legacy_tasks_preview_on_startup: bool = False
    request_timeout_seconds: float = Field(default=60.0, ge=1, le=300)


@lru_cache
def get_settings() -> Settings:
    return Settings()
