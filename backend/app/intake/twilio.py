"""Twilio webhooks: voice (record -> speech-to-text -> pipeline) and SMS.

Every webhook is authenticated with Twilio's request signature: base64
HMAC-SHA1, keyed by the auth token, over the public URL followed by the POST
parameters sorted by name. Twilio signs the URL *it* called (the tunnel), so the
check uses ``PUBLIC_BASE_URL`` rather than the local address.

The recording callback answers Twilio at once and transcribes in the
background, so a slow STT call never makes Twilio time out the webhook.
"""

import asyncio
import base64
import hashlib
import hmac
import logging
from collections.abc import Mapping
from xml.sax.saxutils import escape

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.config import Settings
from app.intake.service import Intake
from app.stt.transcribe import STTChain, STTError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/twilio", tags=["twilio"])

GREETING_HI = "संकेत आपातकालीन सेवा। बीप के बाद बताइए क्या हुआ और आप कहाँ हैं। बोल नहीं सकते तो फ़ोन चालू रखिए।"
GREETING_EN = "Sanket emergency line. After the beep, say what happened and where you are. If you cannot speak, stay on the line."
DOWNLOAD_RETRIES = (0.5, 1.0, 2.0)


def twilio_signature(url: str, params: Mapping[str, str], auth_token: str) -> str:
    """Twilio's X-Twilio-Signature for a form-encoded POST. O(L log p)."""
    payload = url + "".join(key + params[key] for key in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def public_url(request: Request, settings: Settings) -> str:
    if not settings.public_base_url:
        return str(request.url)
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{settings.public_base_url.rstrip('/')}{request.url.path}{query}"


async def verified_form(request: Request) -> dict[str, str]:
    """Parsed webhook form, or 403 if the Twilio signature does not match."""
    settings: Settings = request.app.state.settings
    form = {key: str(value) for key, value in (await request.form()).items()}
    if not settings.twilio_validate_signature:
        return form
    token = settings.twilio_auth_token
    signature = request.headers.get("x-twilio-signature", "")
    if not token or not hmac.compare_digest(twilio_signature(public_url(request, settings), form, token), signature):
        raise HTTPException(403, "invalid Twilio signature")
    return form


def twiml(body: str) -> Response:
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>', media_type="application/xml")


@router.post("/voice")
async def voice(request: Request) -> Response:
    """Greet in Hindi and English, then record up to VOICE_MAX_SECONDS.

    If the caller says nothing, <Record> falls through to the redirect, which
    reports a connected-but-silent call (a silent-SOS signal).
    """
    await verified_form(request)
    settings: Settings = request.app.state.settings
    return twiml(
        f'<Say language="hi-IN" voice="Polly.Aditi">{escape(GREETING_HI)}</Say>'
        f'<Say language="en-IN" voice="Polly.Aditi">{escape(GREETING_EN)}</Say>'
        f'<Record action="/twilio/recording" method="POST" maxLength="{settings.voice_max_seconds}" '
        'timeout="6" playBeep="true" trim="trim-silence" finishOnKey="#"/>'
        '<Redirect method="POST">/twilio/recording</Redirect>'
    )


@router.post("/recording")
async def recording(request: Request) -> Response:
    """Recording finished (or the line stayed silent): acknowledge, then transcribe."""
    form = await verified_form(request)
    task = asyncio.create_task(_process_recording(request.app.state, form))
    request.app.state.voice_tasks.add(task)
    task.add_done_callback(request.app.state.voice_tasks.discard)
    return twiml(
        '<Say language="hi-IN" voice="Polly.Aditi">धन्यवाद। आपकी सूचना दर्ज हो गई है।</Say>'
        '<Say language="en-IN" voice="Polly.Aditi">Thank you. Your report has been recorded.</Say><Hangup/>'
    )


async def _download(http: httpx.AsyncClient, url: str, settings: Settings) -> bytes:
    """Fetch the MP3, retrying briefly while Twilio finalises the recording."""
    auth = (settings.twilio_account_sid, settings.twilio_auth_token) if settings.twilio_account_sid else None
    for delay in (*DOWNLOAD_RETRIES, None):
        response = await http.get(f"{url}.mp3", auth=auth, timeout=15.0)  # type: ignore[arg-type]
        if response.status_code == 200:
            return response.content
        if delay is None or response.status_code != 404:
            response.raise_for_status()
        await asyncio.sleep(delay)
    raise httpx.HTTPError("recording not available")


async def _process_recording(state: object, form: dict[str, str]) -> None:
    settings: Settings = state.settings  # type: ignore[attr-defined]
    intake: Intake = state.intake  # type: ignore[attr-defined]
    stt: STTChain = state.stt  # type: ignore[attr-defined]
    caller = form.get("From")
    url = form.get("RecordingUrl")
    duration = float(form.get("RecordingDuration") or 0)
    text, language = "", None
    try:
        if url and duration > 0:
            audio = await _download(state.http, url, settings)  # type: ignore[attr-defined]
            transcript = await stt.transcribe(audio, "call.mp3", "audio/mpeg", duration)
            text, language = transcript.text, transcript.language
            log.info("call %s transcribed by %s (%s) in %.2fs", form.get("CallSid"), transcript.provider, language, transcript.latency_s)
    except (httpx.HTTPError, STTError) as exc:
        # Never drop a call: an untranscribable recording still reaches a human.
        log.error("call %s could not be transcribed: %s", form.get("CallSid"), exc)
        text = ""
    await intake.submit(text, "call", caller, language)


@router.post("/sms")
async def sms(request: Request) -> Response:
    """Inbound SMS goes straight into the pipeline (also the no-data fallback channel)."""
    form = await verified_form(request)
    settings: Settings = request.app.state.settings
    intake: Intake = request.app.state.intake
    await intake.submit(form.get("Body", ""), "sms", form.get("From"))
    if settings.twilio_sms_reply:
        return twiml("<Message>Sanket: report received. Help is being arranged.</Message>")
    return twiml("")
