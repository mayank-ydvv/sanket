"""LLM provider adapters and per-provider rate limiting.

Two wire formats cover every provider: Gemini ``generateContent`` and the
OpenAI-compatible ``/chat/completions`` (Groq, OpenRouter, and any custom
endpoint such as Jev). Both run in JSON mode over the shared httpx client.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class ProviderReply:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float


class ProviderError(Exception):
    def __init__(
        self, provider: str, message: str, *, retryable: bool, retry_after: float | None = None
    ) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.retryable = retryable
        self.retry_after = retry_after


class Provider(Protocol):
    name: str
    model: str

    async def complete(self, system: str, user: str, max_output_tokens: int) -> ProviderReply: ...


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


async def _post_json(
    client: httpx.AsyncClient,
    provider: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    """POST and decode JSON, mapping transport and HTTP failures to ProviderError."""
    try:
        response = await client.post(url, headers=headers, json=body, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise ProviderError(provider, "timeout", retryable=True) from exc
    except httpx.TransportError as exc:
        raise ProviderError(provider, f"transport error: {exc!r}", retryable=True) from exc
    if response.status_code >= 400:
        detail = " ".join(response.text.split())[:200]
        raise ProviderError(
            provider,
            f"HTTP {response.status_code}: {detail}",
            retryable=response.status_code in RETRYABLE_STATUS,
            retry_after=_retry_after(response),
        )
    try:
        data: dict[str, Any] = response.json()
    except ValueError as exc:
        raise ProviderError(provider, "non-JSON response body", retryable=True) from exc
    return data


class GeminiProvider:
    """Google AI Studio ``generateContent`` with ``responseMimeType: application/json``."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, client: httpx.AsyncClient, api_key: str, model: str, timeout: float) -> None:
        self.name = "gemini"
        self.model = model
        self._client = client
        self._api_key = api_key
        self._timeout = timeout

    async def complete(self, system: str, user: str, max_output_tokens: int) -> ProviderReply:
        start = time.perf_counter()
        data = await _post_json(
            self._client,
            self.name,
            f"{self.BASE_URL}/{self.model}:generateContent",
            headers={"x-goog-api-key": self._api_key},
            body={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0,
                    "maxOutputTokens": max_output_tokens,
                },
            },
            timeout=self._timeout,
        )
        try:
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(self.name, "no candidate text", retryable=True) from exc
        usage = data.get("usageMetadata", {})
        return ProviderReply(
            text=text,
            provider=self.name,
            model=self.model,
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)),
            latency_s=time.perf_counter() - start,
        )


class OpenAICompatibleProvider:
    """Any ``/chat/completions`` endpoint with ``response_format: json_object``."""

    def __init__(
        self,
        name: str,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._client = client
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}", **(extra_headers or {})}
        self._timeout = timeout

    async def complete(self, system: str, user: str, max_output_tokens: int) -> ProviderReply:
        """``max_tokens`` is always explicit: Groq otherwise reserves the model's whole
        output window against its output-tokens-per-minute quota."""
        start = time.perf_counter()
        data = await _post_json(
            self._client,
            self.name,
            self._url,
            headers=self._headers,
            body={
                "model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0,
                "max_tokens": max_output_tokens,
                "response_format": {"type": "json_object"},
            },
            timeout=self._timeout,
        )
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(self.name, "no choices in response", retryable=True) from exc
        usage = data.get("usage") or {}
        return ProviderReply(
            text=text,
            provider=self.name,
            model=self.model,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            latency_s=time.perf_counter() - start,
        )


class TokenBucket:
    """Continuous-refill token bucket. All operations O(1)."""

    def __init__(self, per_minute: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._rate = per_minute / 60.0
        self._capacity = float(per_minute)
        self._tokens = float(per_minute)
        self._clock = clock
        self._updated = clock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._rate)
        self._updated = now

    def wait_time(self, amount: float) -> float:
        """Seconds until ``amount`` tokens are available (0 if available now)."""
        self._refill()
        deficit = min(amount, self._capacity) - self._tokens
        return max(0.0, deficit / self._rate)

    def take(self, amount: float) -> None:
        """Consume tokens; the balance may go negative, which delays later callers."""
        self._refill()
        self._tokens -= min(amount, self._capacity)


class RateLimiter:
    """Request, total-token and (optional) output-token buckets for one provider/model."""

    def __init__(
        self,
        rpm: float,
        tpm: float,
        otpm: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._requests = TokenBucket(rpm, clock)
        self._tokens = TokenBucket(tpm, clock)
        self._output = TokenBucket(otpm, clock) if otpm else None
        self.max_output_tokens = int(otpm) if otpm else None

    def reserve(self, est_input: int, est_output: int, max_wait_s: float) -> float | None:
        """Reserve one request; return the wait in seconds, or None if it exceeds ``max_wait_s``."""
        waits = [self._requests.wait_time(1), self._tokens.wait_time(est_input + est_output)]
        if self._output is not None:
            waits.append(self._output.wait_time(est_output))
        wait = max(waits)
        if wait > max_wait_s:
            return None
        self._requests.take(1)
        self._tokens.take(est_input + est_output)
        if self._output is not None:
            self._output.take(est_output)
        return wait
