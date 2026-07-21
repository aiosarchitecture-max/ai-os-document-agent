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
    # Optional human-readable Google Sheets task register. PostgreSQL remains authoritative.
    task_register_spreadsheet_id: str = ""
    task_register_sheet_name: str = "AI_OS_TASKS"
    # Configure the register independently from write activation so readiness
    # and reconciliation can run before any external row is appended.
    task_register_dual_write_enabled: bool = False
    # The legacy snapshot preview is read-only and safe to run when Render has
    # not synchronized a newly added render.yaml environment variable yet.
    legacy_tasks_preview_on_startup: bool = True
    # The approved one-time migration completed on 2026-07-21. Keep writes
    # disabled by default; the read-only preview remains available.
    legacy_tasks_apply_on_startup: bool = False
    request_timeout_seconds: float = Field(default=60.0, ge=1, le=300)


@lru_cache
def get_settings() -> Settings:
    return Settings()
