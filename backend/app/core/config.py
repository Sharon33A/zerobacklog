"""Centralized, environment-backed application settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__

BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Validated runtime settings.

    Credentials and connection strings use ``SecretStr`` so accidental model
    representations do not disclose their values.
    """

    service_name: str = "zerobacklog-api"
    app_version: str = __version__
    app_env: str = "development"
    frontend_url: str = "http://localhost:3000"
    log_level: str = "INFO"
    gemini_model: str = "gemini-2.5-flash"
    gemini_tts_model: str = "gemini-2.5-flash-preview-tts"
    gemini_voice_name: str = "Kore"
    generation_confidence_threshold: float = 0.72

    gemini_api_key: SecretStr | None = Field(default=None, repr=False)
    youtube_api_key: SecretStr | None = Field(default=None, repr=False)
    database_url: SecretStr | None = Field(default=None, repr=False)
    b2_application_key_id: SecretStr | None = Field(default=None, repr=False)
    b2_application_key: SecretStr | None = Field(default=None, repr=False)
    b2_bucket_name: str | None = None
    b2_endpoint: str | None = None
    b2_region: str | None = None
    max_upload_size_bytes: int = 25 * 1024 * 1024
    infrastructure_retry_attempts: int = 3
    max_link_snapshot_bytes: int = 1024 * 1024
    max_analysis_source_chars: int = 24_000
    max_analysis_total_chars: int = 120_000

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIRECTORY / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("app_env", mode="before")
    @classmethod
    def normalize_environment(cls, value: object) -> str:
        normalized = str(value).strip().lower()
        return normalized or "development"

    @field_validator("frontend_url", mode="before")
    @classmethod
    def normalize_frontend_url(cls, value: object) -> str:
        normalized = str(value).strip().rstrip("/")
        return normalized or "http://localhost:3000"

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> str:
        normalized = str(value).strip().upper()
        allowed_levels = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        return normalized if normalized in allowed_levels else "INFO"

    @property
    def cors_origins(self) -> list[str]:
        """Allow a comma-delimited set of explicitly configured origins."""
        return [
            origin.strip().rstrip("/")
            for origin in self.frontend_url.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Return a single validated settings instance per process."""
    return Settings()
