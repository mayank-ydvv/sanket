"""Application settings, loaded from the environment and ``sanket/.env``."""

import hashlib
import hmac
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models import Contact, Price

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """All runtime configuration. Secrets have no defaults and must come from the env."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", env_ignore_empty=True)  # "KEY=" means unset

    caller_salt: str = Field(min_length=16)
    # Dispatcher accounts. Without SESSION_SECRET, one is derived from CALLER_SALT.
    session_secret: str | None = Field(None, min_length=16)
    session_ttl_s: float = Field(7 * 24 * 3600, gt=0)
    cookie_secure: bool = False  # set true when served over https
    auth_required: bool = True
    # Demo account created by scripts/seed_demo.py (a random password is printed if unset).
    demo_email: str = "demo@sanket.local"
    demo_password: str | None = Field(None, min_length=8)
    db_path: Path = Path("backend/sanket.db")
    local_model_path: Path = Path("backend/artifacts/local_v1.joblib")
    # Demo safety net: record the LLM answers of a live run, replay them with no network.
    demo_record: bool = False
    demo_cache: bool = False
    demo_run_path: Path = Path("backend/data/demo_run.jsonl")
    cors_origins: list[str] = ["http://localhost:5190"]
    ingest_batch_size: int = Field(25, ge=1)
    ingest_batch_wait_ms: int = Field(50, ge=0)
    decide_concurrency: int = Field(8, ge=1)

    # Confidence gates (see README: auto-dispatch / one-click confirm / human review).
    conf_threshold: float = Field(0.8, ge=0.0, le=1.0)

    # System 2 reasoning layer (cross-report linking, merge hints, briefings).
    reasoning_enabled: bool = True
    reasoning_chain: list[str] = ["gemini", "openrouter", "groq"]
    reasoning_gemini_model: str = "gemini-3.5-flash"
    reasoning_debounce_s: float = Field(20.0, ge=0)
    reasoning_min_reports: int = Field(3, ge=1)
    reasoning_min_severity: int = Field(3, ge=1, le=5)
    reasoning_neighbor_m: float = Field(300.0, gt=0)
    reasoning_neighbor_window_s: float = Field(900.0, gt=0)
    reasoning_max_reports: int = Field(30, ge=1)
    reasoning_concurrency: int = Field(2, ge=1)
    reasoning_max_queue_wait_s: float = Field(5.0, ge=0)

    # Geocoding (demo district: Noida). Viewbox is west, south, east, north.
    geo_district: str = "Noida, Uttar Pradesh"
    geo_center: tuple[float, float] = (28.5355, 77.3910)
    geo_viewbox: tuple[float, float, float, float] = (77.25, 28.43, 77.55, 28.70)
    nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    nominatim_user_agent: str = "Sanket-triage-demo/0.1 (hackathon prototype)"
    geocode_network: bool = True
    geocode_max_wait_s: float = Field(3.0, ge=0)

    # Clustering
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    # "sentence" (multilingual MiniLM) or "hashing" (model-free lexical fallback).
    embedding_backend: Literal["sentence", "hashing"] = "sentence"
    # 0.70 + 0.15 department bonus measured best on the 500-report surge (12 ± 2 incidents).
    cluster_similarity: float = Field(0.70, ge=0.0, le=1.0)
    cluster_department_bonus: float = Field(0.15, ge=0.0)
    cluster_radius_km: float = Field(1.0, gt=0)
    cluster_window_s: float = Field(1800.0, gt=0)
    cluster_unlocated_candidates: int = Field(50, ge=1)

    # Cost ticker. List prices in USD per 1M tokens (check providers' pricing pages);
    # the counterfactual is every report sent alone to a large reasoning model.
    llm_prices: dict[str, Price] = {
        "qwen/qwen3.8-27b": Price(input=0.29, output=0.59),
        "gemini-3.5-flash-lite": Price(input=0.10, output=0.40),
        "gemini-3.5-flash": Price(input=0.30, output=2.50),
        "google/gemma-4-31b-it:free": Price(input=0.0, output=0.0),
        "openai/gpt-oss-120b": Price(input=0.15, output=0.60),
    }
    counterfactual_price: Price = Price(input=2.50, output=15.00)
    counterfactual_input_tokens: int = 1550  # full decision prompt + one report
    counterfactual_output_tokens: int = 500  # full JSON answer + reasoning tokens
    usd_to_inr: float = 84.0

    # Telephony intake (Twilio webhooks) and speech-to-text.
    # PUBLIC_BASE_URL is the tunnel URL Twilio calls; signatures are computed over it.
    public_base_url: str | None = None
    twilio_validate_signature: bool = True
    twilio_sms_reply: bool = False
    voice_max_seconds: int = Field(60, ge=5, le=300)
    groq_stt_model: str = "whisper-large-v3"
    sarvam_api_key: str | None = None
    sarvam_stt_model: str = "saaras:v3"

    # Alerts: mock sender unless MOCK_ALERTS=false and Twilio credentials are set.
    mock_alerts: bool = True
    alert_ack_timeout_s: float = Field(90.0, gt=0)
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None
    alert_contacts: dict[str, list[Contact]] = {
        "fire": [Contact(name="Fire station · Sector 6"), Contact(name="District fire officer")],
        "police": [Contact(name="PCR van · Sector 20"), Contact(name="Police control room supervisor")],
        "medical": [Contact(name="108 ambulance dispatch"), Contact(name="CMO duty officer")],
        "disaster": [Contact(name="SDRF team · Noida"), Contact(name="DM control room")],
        "utilities": [Contact(name="UPPCL emergency desk"), Contact(name="Utilities supervisor")],
        "none": [Contact(name="Control room supervisor")],
    }

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

    @field_validator("db_path", "local_model_path", "demo_run_path")
    @classmethod
    def _resolve_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else ROOT / value


def session_secret(settings: Settings) -> str:
    """The configured secret, or a stable one derived from CALLER_SALT (never the salt itself)."""
    if settings.session_secret:
        return settings.session_secret
    return hmac.new(settings.caller_salt.encode(), b"sanket-session-v1", hashlib.sha256).hexdigest()


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (parsed once)."""
    return Settings()  # type: ignore[call-arg]
