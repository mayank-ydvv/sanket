"""Speech-to-text for recorded calls: Groq Whisper first, Sarvam AI as fallback.

Both run over the shared httpx client. Whisper's ``verbose_json`` reports the
detected language by name; Sarvam returns a BCP-47 code. Both are normalised to
the short codes used elsewhere ("hi", "en", "ta", "bn", ...).
"""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx

log = logging.getLogger(__name__)

LANGUAGE_CODES: dict[str, str] = {
    "hindi": "hi",
    "english": "en",
    "tamil": "ta",
    "bengali": "bn",
    "bangla": "bn",
    "marathi": "mr",
    "telugu": "te",
    "gujarati": "gu",
    "kannada": "kn",
    "malayalam": "ml",
    "punjabi": "pa",
    "urdu": "ur",
    "odia": "or",
}
SARVAM_MAX_SECONDS = 30  # Sarvam's real-time REST endpoint limit


def language_code(value: str | None) -> str | None:
    """'hindi' / 'hi' / 'hi-IN' -> 'hi'. O(1)."""
    if not value:
        return None
    lowered = value.strip().lower()
    return LANGUAGE_CODES.get(lowered, lowered.split("-")[0] or None)


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str | None
    provider: str
    latency_s: float


class STTError(Exception):
    pass


class SpeechToText(Protocol):
    name: str

    async def transcribe(
        self, audio: bytes, filename: str, content_type: str, duration_s: float | None
    ) -> Transcript: ...


class GroqWhisper:
    name = "groq-whisper"
    URL = "https://api.groq.com/openai/v1/audio/transcriptions"

    def __init__(self, http: httpx.AsyncClient, api_key: str, model: str, timeout: float = 30.0) -> None:
        self._http = http
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    async def transcribe(
        self, audio: bytes, filename: str, content_type: str, duration_s: float | None
    ) -> Transcript:
        start = time.perf_counter()
        try:
            response = await self._http.post(
                self.URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                files={"file": (filename, audio, content_type)},
                data={"model": self._model, "response_format": "verbose_json", "temperature": "0"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise STTError(f"groq transport error: {exc!r}") from exc
        if response.status_code >= 400:
            raise STTError(f"groq HTTP {response.status_code}: {response.text[:200]}")
        body = response.json()
        return Transcript(
            text=str(body.get("text", "")).strip(),
            language=language_code(body.get("language")),
            provider=self.name,
            latency_s=time.perf_counter() - start,
        )


class SarvamSTT:
    name = "sarvam"
    URL = "https://api.sarvam.ai/speech-to-text"

    def __init__(self, http: httpx.AsyncClient, api_key: str, model: str, timeout: float = 30.0) -> None:
        self._http = http
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    async def transcribe(
        self, audio: bytes, filename: str, content_type: str, duration_s: float | None
    ) -> Transcript:
        if duration_s is not None and duration_s > SARVAM_MAX_SECONDS:
            raise STTError(f"sarvam REST accepts at most {SARVAM_MAX_SECONDS}s of audio")
        start = time.perf_counter()
        try:
            response = await self._http.post(
                self.URL,
                headers={"api-subscription-key": self._api_key},
                files={"file": (filename, audio, content_type)},
                data={"model": self._model, "mode": "transcribe", "language_code": "unknown"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise STTError(f"sarvam transport error: {exc!r}") from exc
        if response.status_code >= 400:
            raise STTError(f"sarvam HTTP {response.status_code}: {response.text[:200]}")
        body = response.json()
        return Transcript(
            text=str(body.get("transcript", "")).strip(),
            language=language_code(body.get("language_code")),
            provider=self.name,
            latency_s=time.perf_counter() - start,
        )


class STTChain:
    """Tries each provider in order; raises STTError only if every one fails."""

    def __init__(self, providers: Sequence[SpeechToText]) -> None:
        self.providers = list(providers)

    async def transcribe(
        self, audio: bytes, filename: str, content_type: str, duration_s: float | None = None
    ) -> Transcript:
        errors: list[str] = []
        for provider in self.providers:
            try:
                return await provider.transcribe(audio, filename, content_type, duration_s)
            except STTError as exc:
                log.warning("STT provider %s failed: %s", provider.name, exc)
                errors.append(str(exc))
        raise STTError("; ".join(errors) or "no speech-to-text provider configured")
