"""Caller-number hashing. Raw phone numbers never reach storage or logs."""

import hashlib
import re

_NON_DIGIT = re.compile(r"[^\d+]")


def hash_caller(caller: str | None, salt: str) -> str | None:
    """Salted SHA-256 of the normalised number (digits and '+' only). O(L)."""
    if not caller:
        return None
    normalised = _NON_DIGIT.sub("", caller)
    if not normalised:
        return None
    return hashlib.sha256(f"{salt}:{normalised}".encode()).hexdigest()
