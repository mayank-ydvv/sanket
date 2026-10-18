"""Accounts and sessions using only the standard library.

* Passwords: scrypt (N=2^14, r=8, p=1) with a per-user random salt.
* Sessions: an HttpOnly cookie holding ``user_id.expiry.signature`` where the
  signature is HMAC-SHA256 under SESSION_SECRET. Nothing is stored server-side,
  so checking a session is O(1) and survives restarts.
* Login throttling: at most 5 failed attempts per email per 5 minutes.
"""

import base64
import hashlib
import hmac
import os
import time
from collections import deque
from collections.abc import Callable

SESSION_COOKIE = "sanket_session"
SCRYPT_N, SCRYPT_R, SCRYPT_P, KEY_LEN = 2**14, 8, 1, 32
MAX_FAILURES, FAILURE_WINDOW_S = 5, 300.0


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_LEN)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check against a stored scrypt hash."""
    try:
        scheme, n, r, p, salt, key = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(key)
        actual = hashlib.scrypt(
            password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _signature(payload: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


def sign_session(user_id: str, secret: str, ttl_s: float, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + ttl_s)
    payload = f"{user_id}.{expires}"
    return f"{payload}.{_signature(payload, secret)}"


def read_session(token: str | None, secret: str, now: float | None = None) -> str | None:
    """User id from a valid, unexpired token; None otherwise. O(1)."""
    if not token or token.count(".") != 2:
        return None
    user_id, expires, signature = token.split(".")
    if not hmac.compare_digest(signature, _signature(f"{user_id}.{expires}", secret)):
        return None
    try:
        if int(expires) < (now if now is not None else time.time()):
            return None
    except ValueError:
        return None
    return user_id


class LoginThrottle:
    """Sliding window of recent failures per key (email). O(1) amortised."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}

    def _recent(self, key: str) -> deque[float]:
        window = self._failures.setdefault(key, deque())
        cutoff = self._clock() - FAILURE_WINDOW_S
        while window and window[0] < cutoff:
            window.popleft()
        return window

    def blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= MAX_FAILURES

    def failed(self, key: str) -> None:
        self._recent(key).append(self._clock())

    def succeeded(self, key: str) -> None:
        self._failures.pop(key, None)
