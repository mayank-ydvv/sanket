"""Check the public Twilio path end to end before a real call.

Posts a correctly signed SMS webhook to PUBLIC_BASE_URL/twilio/sms (through your
tunnel), exactly as Twilio would. A 200 means the tunnel, PUBLIC_BASE_URL and
TWILIO_AUTH_TOKEN all line up; the test report then appears on the board.

Run from ``backend/``: ``python -m scripts.twilio_check``.
"""

import httpx

from app.config import get_settings
from app.intake.twilio import twilio_signature


def main() -> None:
    settings = get_settings()
    if not settings.public_base_url or not settings.twilio_auth_token:
        raise SystemExit("set PUBLIC_BASE_URL and TWILIO_AUTH_TOKEN in sanket/.env first")
    url = f"{settings.public_base_url.rstrip('/')}/twilio/sms"
    form = {"Body": "TEST (twilio_check): Sector 18 metro pe aag lagi hai", "From": "+910000000000"}
    response = httpx.post(
        url,
        data=form,
        headers={"X-Twilio-Signature": twilio_signature(url, form, settings.twilio_auth_token)},
        timeout=15,
    )
    print(f"POST {url} -> {response.status_code}")
    if response.status_code == 403:
        raise SystemExit("signature rejected: PUBLIC_BASE_URL must be exactly the URL Twilio calls")
    response.raise_for_status()
    print("OK: tunnel, URL and auth token are consistent. Point Twilio's webhooks here.")


if __name__ == "__main__":
    main()
