"""Explicit errors for the PayPal client.

Messages carry only safe fields: HTTP status, PayPal's error name, issue codes and
debug_id. PayPal's free-text `message` / `description` fields are left out because
they can echo request or buyer data. Known secrets are also scrubbed from every message.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

REDACTED = "***"


def redact(text: str, secrets: Iterable[str]) -> str:
    """Replace every known secret in `text` with ***."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


class PayPalError(Exception):
    """Base class. The message is safe to show and log."""


class PayPalConfigError(PayPalError):
    """Missing environment variables or a base URL that is not the sandbox."""


class PayPalNetworkError(PayPalError):
    """Timeout, connection failure or an unexpected redirect."""


class PayPalResponseError(PayPalError):
    """A successful HTTP status whose body is not JSON or fails validation."""


class PayPalAPIError(PayPalError):
    """PayPal returned a non-2xx status."""

    def __init__(
        self,
        *,
        method: str,
        path: str,
        http_status: int,
        name: str | None = None,
        issues: list[str] | None = None,
        debug_id: str | None = None,
        secrets: Iterable[str] = (),
    ) -> None:
        self.method = method
        self.path = path
        self.http_status = http_status
        self.name = name
        self.issues = issues or []
        self.debug_id = debug_id
        parts = [f"PayPal {method} {path} failed: HTTP {http_status}"]
        if name:
            parts.append(f"name={name}")
        if self.issues:
            parts.append(f"issues={','.join(self.issues)}")
        if debug_id:
            parts.append(f"debug_id={debug_id}")
        super().__init__(redact(" ".join(parts), list(secrets)))


class PayPalAuthError(PayPalAPIError):
    """The OAuth token request failed."""


def _short(value: Any, limit: int = 100) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return " ".join(value.split())[:limit]


def parse_error_body(body: Any) -> dict[str, Any]:
    """Pick the safe fields out of a PayPal error body (REST or OAuth shape)."""
    if not isinstance(body, dict):
        return {"name": None, "issues": [], "debug_id": None}
    # REST errors use `name`; OAuth errors use `error`.
    name = _short(body.get("name")) or _short(body.get("error"))
    details = body.get("details") if isinstance(body.get("details"), list) else []
    issues = [
        issue
        for issue in (_short(item.get("issue")) for item in details if isinstance(item, dict))
        if issue
    ]
    return {"name": name, "issues": issues, "debug_id": _short(body.get("debug_id"))}
