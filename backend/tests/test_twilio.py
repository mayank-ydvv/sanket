"""Phase 6: Twilio signature validation, voice/SMS webhooks, speech-to-text fallback."""

from collections.abc import Callable
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.intake.twilio import twilio_signature
from app.main import create_app
from app.stt.transcribe import GroqWhisper, SarvamSTT, STTChain, STTError, language_code
from tests.conftest import receive_event

TOKEN = "test-auth-token"
BASE = "https://sanket-demo.example"
RECORDING = "https://api.twilio.com/2010-04-01/Accounts/AC1/Recordings/RE1"


def test_signature_matches_twilio_documented_example() -> None:
    params = {
        "CallSid": "CA1234567890ABCDE",
        "Caller": "+14158675310",
        "Digits": "1234",
        "From": "+14158675310",
        "To": "+18005551212",
    }
    assert twilio_signature("https://mycompany.com/myapp.php?foo=1&bar=2", params, "12345") == "GvWf1cFY/Q7PnoempGyD5oXAezc="


def media_and_stt(
    groq: Callable[[httpx.Request], httpx.Response] | None = None,
) -> tuple[httpx.MockTransport, list[str]]:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "api.twilio.com":
            assert request.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, content=b"ID3fake-mp3")
        if request.url.host == "api.groq.com" and request.url.path.endswith("/audio/transcriptions"):
            if groq is not None:
                return groq(request)
            return httpx.Response(200, json={"text": "सेक्टर 62 में बिल्डिंग में आग लगी है, लोग फंसे हैं", "language": "hindi"})
        return httpx.Response(404)

    return httpx.MockTransport(handler), calls


@pytest.fixture
def twilio_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "twilio_auth_token": TOKEN,
            "twilio_account_sid": "AC1",
            "public_base_url": BASE,
            "groq_api_key": "groq-test",
            "gemini_api_key": None,
            "openrouter_api_key": None,
        }
    )


def signed_post(client: TestClient, path: str, form: dict[str, str], token: str = TOKEN):  # type: ignore[no-untyped-def]
    signature = twilio_signature(f"{BASE}{path}", form, token)
    return client.post(
        path,
        content=urlencode(form),
        headers={"content-type": "application/x-www-form-urlencoded", "x-twilio-signature": signature},
    )


def test_unsigned_or_forged_webhooks_are_rejected(twilio_settings: Settings) -> None:
    transport, _ = media_and_stt()
    with TestClient(create_app(twilio_settings, transport)) as client:
        assert client.post("/twilio/sms", data={"Body": "help", "From": "+911"}).status_code == 403
        assert signed_post(client, "/twilio/sms", {"Body": "help", "From": "+911"}, token="wrong").status_code == 403


def test_voice_webhook_returns_bilingual_record_twiml(twilio_settings: Settings) -> None:
    transport, _ = media_and_stt()
    with TestClient(create_app(twilio_settings, transport)) as client:
        response = signed_post(client, "/twilio/voice", {"CallSid": "CA1", "From": "+919999000001"})
    assert response.status_code == 200 and response.headers["content-type"].startswith("application/xml")
    body = response.text
    assert '<Record action="/twilio/recording"' in body and 'maxLength="60"' in body
    assert 'language="hi-IN"' in body and "<Redirect" in body


def test_recorded_hindi_call_becomes_a_report(twilio_settings: Settings) -> None:
    transport, calls = media_and_stt()
    with TestClient(create_app(twilio_settings, transport)) as client, client.websocket_connect("/ws") as ws:
        response = signed_post(
            client,
            "/twilio/recording",
            {"CallSid": "CA1", "From": "+919999000001", "RecordingUrl": RECORDING, "RecordingDuration": "7"},
        )
        assert "<Hangup/>" in response.text
        report = receive_event(ws, "report.created")["data"]
    assert report["channel"] == "call" and report["language"] == "hi"
    assert report["raw_text"].startswith("सेक्टर 62")
    assert report["decision"]["severity"] >= 3  # trapped people: life-safety floor
    assert report["lat"] is not None  # "सेक्टर 62" resolved by the gazetteer
    assert any(c.endswith("RE1.mp3") for c in calls)


def test_silent_connected_call_is_a_silent_sos(twilio_settings: Settings) -> None:
    transport, calls = media_and_stt()
    with TestClient(create_app(twilio_settings, transport)) as client, client.websocket_connect("/ws") as ws:
        signed_post(client, "/twilio/recording", {"CallSid": "CA2", "From": "+919999000002"})  # no recording
        report = receive_event(ws, "report.created")["data"]
    assert report["channel"] == "call" and report["raw_text"] == ""
    assert report["decision"]["silent_sos"] and report["decision"]["department"] == "police"
    assert report["flags"] == ["silent_sos:empty_call"]
    assert not calls  # nothing to download or transcribe


def test_failed_transcription_still_reaches_a_human(twilio_settings: Settings) -> None:
    transport, _ = media_and_stt(groq=lambda request: httpx.Response(500, text="boom"))
    with TestClient(create_app(twilio_settings, transport)) as client, client.websocket_connect("/ws") as ws:
        signed_post(client, "/twilio/recording", {"CallSid": "CA3", "From": "+91999", "RecordingUrl": RECORDING, "RecordingDuration": "5"})
        report = receive_event(ws, "report.created")["data"]
    assert report["channel"] == "call" and report["decision"]["needs_human_review"]


def test_sms_goes_into_the_pipeline(twilio_settings: Settings) -> None:
    transport, _ = media_and_stt()
    with TestClient(create_app(twilio_settings, transport)) as client, client.websocket_connect("/ws") as ws:
        response = signed_post(client, "/twilio/sms", {"Body": "Sector 18 metro pe aag lagi hai", "From": "+919999000003"})
        assert response.status_code == 200 and response.text.endswith("<Response></Response>")
        report = receive_event(ws, "report.created")["data"]
    assert report["channel"] == "sms" and report["raw_text"] == "Sector 18 metro pe aag lagi hai"
    assert report["caller_hash"] and "9999000003" not in str(report)


async def test_stt_falls_back_from_groq_to_sarvam() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.groq.com":
            return httpx.Response(429, text="rate limited")
        assert request.headers["api-subscription-key"] == "sarvam-test"
        return httpx.Response(200, json={"transcript": "আগুন লেগেছে", "language_code": "bn-IN"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    chain = STTChain([GroqWhisper(http, "g", "whisper-large-v3"), SarvamSTT(http, "sarvam-test", "saaras:v3")])
    transcript = await chain.transcribe(b"audio", "call.mp3", "audio/mpeg", 12)
    assert (transcript.text, transcript.language, transcript.provider) == ("আগুন লেগেছে", "bn", "sarvam")
    with pytest.raises(STTError):
        await STTChain([SarvamSTT(http, "sarvam-test", "saaras:v3")]).transcribe(b"a", "c.mp3", "audio/mpeg", 45)


def test_language_codes() -> None:
    assert [language_code(v) for v in ("hindi", "hi-IN", "Tamil", None)] == ["hi", "hi", "ta", None]
