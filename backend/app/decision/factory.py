"""Builds the fast-LLM decider from settings. Providers without a key are skipped."""

import httpx

from app.config import Settings
from app.decision.llm import FallbackChain, LLMDecider, LLMStats, ProviderSlot
from app.decision.providers import GeminiProvider, OpenAICompatibleProvider, Provider, RateLimiter


def build_slots(settings: Settings, http: httpx.AsyncClient) -> list[ProviderSlot]:
    """Fallback order: Gemini -> Groq -> OpenRouter -> custom OpenAI-compatible."""
    timeout = settings.llm_timeout_s
    slots: list[tuple[Provider, int, int]] = []
    if settings.gemini_api_key:
        slots.append(
            (
                GeminiProvider(http, settings.gemini_api_key, settings.gemini_model, timeout),
                settings.gemini_rpm,
                settings.gemini_tpm,
            )
        )
    if settings.groq_api_key:
        slots.append(
            (
                OpenAICompatibleProvider(
                    "groq", http, "https://api.groq.com/openai/v1", settings.groq_api_key,
                    settings.groq_model, timeout,
                ),
                settings.groq_rpm,
                settings.groq_tpm,
            )
        )
    if settings.openrouter_api_key:
        slots.append(
            (
                OpenAICompatibleProvider(
                    "openrouter", http, "https://openrouter.ai/api/v1", settings.openrouter_api_key,
                    settings.openrouter_model, timeout, extra_headers={"X-Title": "Sanket"},
                ),
                settings.openrouter_rpm,
                settings.openrouter_tpm,
            )
        )
    if settings.custom_llm_base_url and settings.custom_llm_api_key and settings.custom_llm_model:
        slots.append(
            (
                OpenAICompatibleProvider(
                    "custom", http, settings.custom_llm_base_url, settings.custom_llm_api_key,
                    settings.custom_llm_model, timeout,
                ),
                settings.custom_llm_rpm,
                settings.custom_llm_tpm,
            )
        )
    return [ProviderSlot(provider, RateLimiter(rpm, tpm)) for provider, rpm, tpm in slots]


def build_llm_decider(settings: Settings, http: httpx.AsyncClient) -> LLMDecider | None:
    slots = build_slots(settings, http)
    if not slots:
        return None
    stats = LLMStats()
    chain = FallbackChain(slots, stats, settings.llm_max_queue_wait_s)
    return LLMDecider(
        chain,
        stats,
        batch_size=settings.llm_batch_size,
        batch_wait_s=settings.llm_batch_wait_ms / 1000,
        max_concurrency=settings.llm_max_concurrency,
    )
