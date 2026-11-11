"""CSRF tokens for the approval page's forms (T-006, ADR-010).

A token is `ts.nonce.mac`, where mac = HMAC-SHA256(key, "dispute_id|purpose|ts|nonce").
The key is random per process and never written anywhere. A token is valid for one
dispute and one purpose (draft or approve), for TTL_SECONDS, and only once: used nonces
are kept in memory until they would have expired anyway. No cookies are needed: the app
has no login, and another site cannot read a token out of the page.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
from collections.abc import Callable

TTL_SECONDS = 15 * 60
CLOCK_SKEW_SECONDS = 60
_TOKEN = re.compile(r"^([0-9]{1,12})\.([A-Za-z0-9_-]{16,64})\.([0-9a-f]{64})$")


class CsrfTokens:
    def __init__(
        self,
        key: bytes | None = None,
        *,
        ttl_seconds: int = TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._key = key if key is not None else secrets.token_bytes(32)
        if len(self._key) < 32:
            raise ValueError("CSRF key must be at least 32 bytes")
        self._ttl = ttl_seconds
        self._clock = clock
        self._used: dict[str, float] = {}  # nonce -> time after which it would be expired anyway
        self._lock = threading.Lock()

    def _mac(self, dispute_id: str, purpose: str, ts: str, nonce: str) -> str:
        message = f"{dispute_id}|{purpose}|{ts}|{nonce}".encode()
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def issue(self, dispute_id: str, purpose: str) -> str:
        ts = str(int(self._clock()))
        nonce = secrets.token_urlsafe(16)
        return f"{ts}.{nonce}.{self._mac(dispute_id, purpose, ts, nonce)}"

    def consume(self, token: object, dispute_id: str, purpose: str) -> bool:
        """True once for a valid, unexpired token for this dispute and purpose; False otherwise."""
        if not isinstance(token, str):
            return False
        match = _TOKEN.fullmatch(token)
        if match is None:
            return False
        ts, nonce, mac = match.groups()
        if not hmac.compare_digest(self._mac(dispute_id, purpose, ts, nonce), mac):
            return False
        now = self._clock()
        issued = int(ts)
        if issued > now + CLOCK_SKEW_SECONDS or now - issued > self._ttl:
            return False
        with self._lock:
            self._used = {n: until for n, until in self._used.items() if until >= now}
            if nonce in self._used:
                return False
            self._used[nonce] = issued + self._ttl
        return True
