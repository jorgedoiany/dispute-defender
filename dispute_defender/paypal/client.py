"""PayPal REST client for the Disputes API. Sandbox only.

Adapted from scripts/spike_sandbox.py (T-002). Every response is validated with the
models in `models.py`; every failure raises a `PayPalError` subclass whose message
never contains credentials, tokens or buyer details.
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

import requests
from pydantic import BaseModel, ValidationError

from .config import PayPalConfig, load_config
from .errors import (
    PayPalAPIError,
    PayPalAuthError,
    PayPalNetworkError,
    PayPalResponseError,
    parse_error_body,
    redact,
)
from .models import AccessToken, ActionAck, Dispute, DisputeList, DisputeListItem, Evidence

TOKEN_PATH = "/v1/oauth2/token"
DISPUTES_PATH = "/v1/customer/disputes"
DEFAULT_TIMEOUT_SECONDS = 30.0
TOKEN_REFRESH_MARGIN_SECONDS = 60
MAX_PAGE_SIZE = 50
_DISPUTE_ID = re.compile(r"[A-Za-z0-9-]{1,64}")

M = TypeVar("M", bound=BaseModel)


def check_dispute_id(dispute_id: str) -> str:
    """Allow only letters, digits and hyphens, so an ID cannot change the URL path."""
    if not isinstance(dispute_id, str) or not _DISPUTE_ID.fullmatch(dispute_id):
        raise ValueError("dispute_id must be 1-64 letters, digits or hyphens")
    return dispute_id


class PayPalClient:
    """Calls the PayPal sandbox. The OAuth token is fetched on first use and cached."""

    def __init__(
        self,
        config: PayPalConfig,
        *,
        session: requests.Session | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._session = session or requests.Session()
        self._timeout = timeout
        self._clock = clock
        self._token: AccessToken | None = None
        self._token_expires_at = 0.0

    @classmethod
    def from_env(cls, **kwargs: Any) -> PayPalClient:
        """Build a client from PAYPAL_* environment variables."""
        return cls(load_config(), **kwargs)

    # --- public API -------------------------------------------------------

    def get_token(self) -> AccessToken:
        """Return a valid token, requesting a new one if none is cached or it is about to expire."""
        if self._token is None or self._clock() >= self._token_expires_at:
            self._token = self._request_token()
            self._token_expires_at = (
                self._clock() + self._token.expires_in - TOKEN_REFRESH_MARGIN_SECONDS
            )
        return self._token

    def list_disputes(self, page_size: int = 20) -> list[DisputeListItem]:
        """First page of the merchant's disputes (no pagination)."""
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        body = self._call("GET", DISPUTES_PATH, params={"page_size": page_size})
        return list(self._validate(DisputeList, body, "GET", DISPUTES_PATH).items)

    def get_dispute(self, dispute_id: str) -> Dispute:
        path = f"{DISPUTES_PATH}/{check_dispute_id(dispute_id)}"
        return self._validate(Dispute, self._call("GET", path), "GET", path)

    def get_dispute_raw(self, dispute_id: str) -> dict[str, Any]:
        """Unvalidated dispute JSON. For diagnostics only (smoke script key names); never use for claims."""
        path = f"{DISPUTES_PATH}/{check_dispute_id(dispute_id)}"
        return self._call("GET", path)

    def send_message(self, dispute_id: str, message: str) -> ActionAck:
        """Send a message to the buyer. Uses a JSON body, which the sandbox accepted in T-002."""
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must not be empty")
        path = f"{DISPUTES_PATH}/{check_dispute_id(dispute_id)}/send-message"
        body = self._call("POST", path, json={"message": message})
        return self._validate(ActionAck, body, "POST", path)

    def provide_evidence(self, dispute_id: str, evidences: Sequence[Evidence]) -> ActionAck:
        """Submit evidence as multipart with one JSON part named `input` (no files)."""
        if not evidences or not all(isinstance(item, Evidence) for item in evidences):
            raise ValueError("evidences must be a non-empty sequence of Evidence")
        path = f"{DISPUTES_PATH}/{check_dispute_id(dispute_id)}/provide-evidence"
        payload = {"evidences": [item.to_payload() for item in evidences]}
        files = {"input": (None, json.dumps(payload), "application/json")}
        body = self._call("POST", path, files=files)
        return self._validate(ActionAck, body, "POST", path)

    # --- internals --------------------------------------------------------

    def _secrets(self) -> list[str]:
        secrets = [self._config.client_id, self._config.client_secret]
        if self._token is not None:
            secrets.append(self._token.access_token.get_secret_value())
        return secrets

    def _request_token(self) -> AccessToken:
        status, body = self._send(
            "POST",
            TOKEN_PATH,
            auth=(self._config.client_id, self._config.client_secret),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
        )
        if status != 200:
            raise PayPalAuthError(
                method="POST", path=TOKEN_PATH, http_status=status,
                secrets=self._secrets(), **parse_error_body(body),
            )
        return self._validate(AccessToken, body, "POST", TOKEN_PATH)

    def _call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        token = self.get_token().access_token.get_secret_value()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        status, body = self._send(method, path, headers=headers, **kwargs)
        if not 200 <= status < 300:
            raise PayPalAPIError(
                method=method, path=path, http_status=status,
                secrets=self._secrets(), **parse_error_body(body),
            )
        if not isinstance(body, dict):
            raise PayPalResponseError(f"PayPal {method} {path}: HTTP {status} body is not a JSON object")
        return body

    def _send(self, method: str, path: str, **kwargs: Any) -> tuple[int, Any]:
        try:
            response = self._session.request(
                method, self._config.base_url + path,
                timeout=self._timeout, allow_redirects=False, **kwargs,
            )
        except requests.RequestException as exc:
            raise PayPalNetworkError(f"network error on {method} {path}: {type(exc).__name__}") from None
        if 300 <= response.status_code < 400:
            raise PayPalNetworkError(
                f"unexpected redirect on {method} {path}: HTTP {response.status_code} (not followed)"
            )
        if not response.content:
            return response.status_code, {}
        try:
            return response.status_code, response.json()
        except ValueError:
            if 200 <= response.status_code < 300:
                raise PayPalResponseError(
                    f"PayPal {method} {path}: HTTP {response.status_code} body is not JSON"
                ) from None
            return response.status_code, None

    def _validate(self, model: type[M], body: Any, method: str, path: str) -> M:
        try:
            return model.model_validate(body)
        except ValidationError as exc:
            # Field locations and error types only; input values are never included.
            problems = "; ".join(
                f"{'.'.join(str(part) for part in err['loc']) or '<body>'}: {err['type']}"
                for err in exc.errors(include_input=False, include_url=False)
            )
            message = f"PayPal {method} {path}: response failed validation ({problems})"
            raise PayPalResponseError(redact(message, self._secrets())[:500]) from None
