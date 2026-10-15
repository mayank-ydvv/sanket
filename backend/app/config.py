"""Application settings, loaded from the environment and ``sanket/.env``."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """All runtime configuration. Secrets have no defaults and must come from the env."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    caller_salt: str = Field(min_length=16)
    db_path: Path = Path("backend/sanket.db")
    local_model_path: Path = Path("backend/artifacts/local_v1.joblib")
    cors_origins: list[str] = ["http://localhost:5190"]
    ingest_batch_size: int = Field(25, ge=1)
    ingest_batch_wait_ms: int = Field(50, ge=0)

    @field_validator("db_path", "local_model_path")
    @classmethod
    def _resolve_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else ROOT / value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (parsed once)."""
    return Settings()  # type: ignore[call-arg]
