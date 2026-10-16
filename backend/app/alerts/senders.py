"""Alert delivery: a recording mock for demos/tests and Twilio SMS over the shared client."""

import logging
from typing import Protocol

import httpx

from app.models import Contact

log = logging.getLogger(__name__)


class AlertSendError(Exception):
    pass


class AlertSender(Protocol):
    channel: str

    async def send(self, contact: Contact, message: str) -> None: ...


class MockSender:
    """Logs and records every alert instead of sending it (MOCK_ALERTS=true)."""

    channel = "mock"

    def __init__(self) -> None:
        self.sent: list[tuple[Contact, str]] = []

    async def send(self, contact: Contact, message: str) -> None:
        self.sent.append((contact, message))
        log.info("ALERT -> %s: %s", contact.name, message)


class TwilioSmsSender:
    """Twilio Messages API (trial accounts can only text verified numbers)."""

    channel = "sms"

    def __init__(self, http: httpx.AsyncClient, account_sid: str, auth_token: str, from_number: str) -> None:
        self._http = http
        self._url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        self._auth = (account_sid, auth_token)
        self._from = from_number

    async def send(self, contact: Contact, message: str) -> None:
        if not contact.phone:
            raise AlertSendError(f"contact {contact.name!r} has no phone number")
        try:
            response = await self._http.post(
                self._url,
                auth=self._auth,
                data={"To": contact.phone, "From": self._from, "Body": message[:1500]},
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            raise AlertSendError(f"twilio transport error: {exc!r}") from exc
        if response.status_code >= 400:
            raise AlertSendError(f"twilio HTTP {response.status_code}: {response.text[:200]}")
