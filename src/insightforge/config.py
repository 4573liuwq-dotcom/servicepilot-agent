from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized, environment-driven application settings."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_name: str = "ServicePilot After-sales Agent"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"

    llm_api_key: SecretStr = Field(default=SecretStr("demo-key"))
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4.1-mini"
    llm_temperature: float = 0.1
    llm_timeout_seconds: float = 60.0
    demo_mode: bool = True

    tavily_api_key: SecretStr | None = None
    app_api_key: SecretStr | None = None
    require_plan_approval: bool = False
    max_reflection_loops: int = Field(default=2, ge=0, le=5)
    quality_threshold: int = Field(default=80, ge=0, le=100)
    max_query_chars: int = Field(default=4000, ge=100, le=20000)
    database_path: Path = Path("data/insightforge.db")


@lru_cache
def get_settings() -> Settings:
    return Settings()
