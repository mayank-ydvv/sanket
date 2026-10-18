"""Builds the fast-LLM decider from settings. Providers without a key are skipped."""

from collections.abc import Sequence

import httpx

from app.config import Settings
from app.decision.llm import FallbackChain, LLMDecider, LLMStats, ProviderSlot
from app.demo import DemoRecorder
from app.decision.providers import GeminiProvider, OpenAICompatibleProvider, Provider, RateLimiter


def build_slots(
    settings: Settings,
    http: httpx.AsyncClient,
    *,
    order: Sequence[str] | None = None,
    gemini_models: Sequence[str] | None = None,
    limiters: dict[str, RateLimiter] | None = None,
) -> list[ProviderSlot]:
    """Providers with a key, in ``order`` (default ``settings.llm_chain``: Groq first, fastest).

    ``limiters`` is shared between chains so the fast path and the reasoning layer
    draw on one quota per provider/model instead of each assuming it has it all.
    """
    timeout = settings.llm_timeout_s
    shared = {} if limiters is None else limiters
    slots: list[tuple[Provider, int, int, int | None]] = []
    if settings.gemini_api_key:
        for model in gemini_models if gemini_models is not None else settings.gemini_models:
            slots.append(
                (
                    GeminiProvider(http, settings.gemini_api_key, model, timeout),
                    settings.gemini_rpm,
                    settings.gemini_tpm,
                    None,
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
                settings.groq_otpm,
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
                None,
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
                None,
            )
        )
    rank = {name: i for i, name in enumerate(order if order is not None else settings.llm_chain)}
    ordered = sorted((s for s in slots if s[0].name in rank), key=lambda s: rank[s[0].name])
    return [
        ProviderSlot(provider, shared.setdefault(f"{provider.name}/{provider.model}", RateLimiter(rpm, tpm, otpm)))
        for provider, rpm, tpm, otpm in ordered
    ]


def build_llm_decider(
    settings: Settings,
    http: httpx.AsyncClient,
    limiters: dict[str, RateLimiter] | None = None,
    recorder: DemoRecorder | None = None,
) -> LLMDecider | None:
    slots = build_slots(settings, http, limiters=limiters)
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
        recorder=recorder,
    )


def build_reasoning_chain(
    settings: Settings, http: httpx.AsyncClient, limiters: dict[str, RateLimiter] | None = None
) -> FallbackChain | None:
    """System 2 chain: Gemini Flash first, then the free OpenRouter model, then Groq."""
    slots = build_slots(
        settings,
        http,
        order=settings.reasoning_chain,
        gemini_models=[settings.reasoning_gemini_model],
        limiters=limiters,
    )
    return FallbackChain(slots, LLMStats(), settings.reasoning_max_queue_wait_s) if slots else None
