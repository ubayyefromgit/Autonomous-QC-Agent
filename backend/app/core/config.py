"""Centralized Pydantic V2 configuration for the QC Intelligence Platform."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "Autonomous QC & Project Audit Intelligence Platform"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = "development"
    API_V1_STR: str = "/api/v1"

    SECRET_KEY: str = "qc-platform-production-grade-secret-key-change-in-prod-9f8e7d6c5b4a"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    DATABASE_URL: str = "postgresql+asyncpg://postgres@127.0.0.1:5433/qc_platform"
    SYNC_DATABASE_URL: str = "postgresql+psycopg2://postgres@127.0.0.1:5433/qc_platform"
    TEST_DATABASE_URL: str = "postgresql+asyncpg://postgres@127.0.0.1:5433/qc_platform_test"

    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    STORAGE_ROOT: str = ".qc_storage"
    WORKSPACE_ROOT: str = ".qc_workspaces"

    DEFAULT_LLM_PROVIDER: str = "ollama"
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "qwen2.5-coder:7b"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-pro"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    GITHUB_TOKEN: str = ""

    DEFAULT_RUNNER_MODE: str = "LOCAL"
    COMMAND_TIMEOUT_SECONDS: int = 120
    MAX_CONCURRENT_TASKS: int = 4

    @property
    def storage_path(self) -> Path:
        path = Path(self.STORAGE_ROOT).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def workspace_path(self) -> Path:
        path = Path(self.WORKSPACE_ROOT).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
