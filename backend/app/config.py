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
    decide_concurrency: int = Field(8, ge=1)

    # Confidence gates (see README: auto-dispatch / one-click confirm / human review).
    conf_threshold: float = Field(0.8, ge=0.0, le=1.0)

    # Rules
    prank_window_s: float = Field(600.0, gt=0)
    prank_min_reports: int = Field(3, ge=1)

    # Fast LLM (System 1 fallback). A provider is enabled when its key is set.
    llm_batch_size: int = Field(25, ge=1)
    llm_batch_wait_ms: int = Field(300, ge=0)
    llm_max_concurrency: int = Field(4, ge=1)
    llm_timeout_s: float = Field(15.0, gt=0)
    llm_chain: list[str] = ["groq", "gemini", "openrouter", "custom"]
    llm_max_queue_wait_s: float = Field(1.5, ge=0)
    gemini_api_key: str | None = None
    # Free quotas are per model, so each listed model is its own fallback slot.
    gemini_models: list[str] = ["gemini-3.5-flash-lite", "gemini-3.5-flash"]
    gemini_rpm: int = 10
    gemini_tpm: int = 250_000
    groq_api_key: str | None = None
    groq_model: str = "qwen/qwen3.8-27b"
    groq_rpm: int = 30
    groq_tpm: int = 8_000
    groq_otpm: int | None = 1_000
    openrouter_api_key: str | None = None
    openrouter_model: str = "google/gemma-4-31b-it:free"
    openrouter_rpm: int = 20
    openrouter_tpm: int = 100_000
    custom_llm_base_url: str | None = None
    custom_llm_api_key: str | None = None
    custom_llm_model: str | None = None
    custom_llm_rpm: int = 30
    custom_llm_tpm: int = 100_000

    @field_validator("db_path", "local_model_path")
    @classmethod
    def _resolve_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else ROOT / value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (parsed once)."""
    return Settings()  # type: ignore[call-arg]
