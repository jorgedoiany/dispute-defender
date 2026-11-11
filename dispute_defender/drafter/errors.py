"""Typed drafter errors (T-005, ADR-009).

Every message is safe to show and log. It may hold an error code, an HTTP status,
an AWS request ID, an attempt count, or pydantic field locations and error types.
It never holds the prompt, model output values, AWS's free-text error message or
credentials.
"""
from __future__ import annotations

import re

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")


def safe_token(value: object) -> str:
    """Return `value` if it is a short plain token (error code, request ID), else 'unknown'."""
    return value if isinstance(value, str) and _SAFE_TOKEN.fullmatch(value) else "unknown"


class DrafterError(Exception):
    """Base class. The message is safe to show and log."""


class ModelConfigError(DrafterError):
    """Missing or invalid environment variables, or no AWS credentials found."""


class ModelNetworkError(DrafterError):
    """Timeout or connection failure. Not retried."""


class ModelCallError(DrafterError):
    """Bedrock refused the call (any error other than throttling). Not retried."""

    def __init__(self, *, code: object, http_status: object = None, request_id: object = None) -> None:
        self.code = safe_token(code)
        self.http_status = http_status if isinstance(http_status, int) else None
        self.request_id = safe_token(request_id) if request_id else None
        parts = [f"Bedrock Converse failed: code={self.code}"]
        if self.http_status is not None:
            parts.append(f"http={self.http_status}")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        super().__init__(" ".join(parts))


class ModelThrottledError(DrafterError):
    """Bedrock was still throttling after the bounded retries."""

    def __init__(self, *, attempts: int, request_id: object = None) -> None:
        self.attempts = attempts
        self.request_id = safe_token(request_id) if request_id else None
        suffix = f" request_id={self.request_id}" if self.request_id else ""
        super().__init__(f"Bedrock Converse throttled after {attempts} attempts{suffix}")


class DraftRejected(DrafterError):
    """The model output cannot be used. Nothing from it is passed on."""
