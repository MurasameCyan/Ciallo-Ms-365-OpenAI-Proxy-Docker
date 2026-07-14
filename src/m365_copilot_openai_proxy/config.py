from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    access_token: str = Field(default="", alias="M365_ACCESS_TOKEN")
    time_zone: str = Field(default="Asia/Shanghai", alias="M365_TIME_ZONE")
    model_alias: str = Field(default="m365-copilot", alias="M365_MODEL_ALIAS")
    api_key: str = Field(default="", alias="API_KEY")
    admin_password: str = Field(default="", alias="ADMIN_PASSWORD")
    idle_timeout_minutes: int = Field(default=30, alias="IDLE_TIMEOUT_MINUTES")
    token_dir: str = Field(default="/home/app/token", alias="TOKEN_DIR")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    # Runtime user/account log toggles. Seed the initial value of the (Web-editable)
    # runtime settings; the runtime settings file wins once written.
    log_user_verbose: bool = Field(default=True, alias="LOG_USER_VERBOSE")
    log_user_errors: bool = Field(default=True, alias="LOG_USER_ERRORS")
    # Suppress high-frequency uvicorn access-log lines (admin/user polling, health
    # checks, favicon, root, media proxy). On by default; the admin UI can flip it.
    suppress_access_log: bool = Field(default=True, alias="SUPPRESS_ACCESS_LOG")
    # Whether to run the shared admin CDP Chromium on the primary port (9222) and
    # register the admin endpoints that depend on it. Off by default: pool
    # deployments drive per-account Chromium on their own ports instead.
    enable_admin_cdp: bool = Field(default=False, alias="ENABLE_ADMIN_CDP")
