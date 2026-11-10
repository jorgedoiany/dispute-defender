"""PayPal client configuration, read from environment variables only. Sandbox only."""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .errors import PayPalConfigError

SANDBOX_HOST = "api-m.sandbox.paypal.com"
SANDBOX_BASE_URL = f"https://{SANDBOX_HOST}"

ENV_CLIENT_ID = "PAYPAL_CLIENT_ID"
ENV_CLIENT_SECRET = "PAYPAL_CLIENT_SECRET"
ENV_BASE_URL = "PAYPAL_BASE_URL"


@dataclass(frozen=True)
class PayPalConfig:
    """Credentials and base URL for the PayPal sandbox. The secret is hidden from repr."""

    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    base_url: str = SANDBOX_BASE_URL

    def __post_init__(self) -> None:
        check_sandbox_url(self.base_url)


def check_sandbox_url(base_url: str) -> None:
    """Refuse any base URL other than https://api-m.sandbox.paypal.com."""
    parts = urlsplit(base_url)
    if (
        parts.scheme != "https"
        or parts.hostname != SANDBOX_HOST
        or parts.port is not None
        or parts.path
        or parts.query
        or parts.fragment
        or parts.username
        or parts.password
    ):
        raise PayPalConfigError(f"refusing to run: {ENV_BASE_URL} must be {SANDBOX_BASE_URL}")


def load_config(env: Mapping[str, str] | None = None) -> PayPalConfig:
    """Build a config from environment variables (os.environ by default).

    This does not read `.env`; the app entry point loads it into the environment.
    """
    source = os.environ if env is None else env
    client_id = source.get(ENV_CLIENT_ID, "").strip()
    client_secret = source.get(ENV_CLIENT_SECRET, "").strip()
    missing = [
        name for name, value in ((ENV_CLIENT_ID, client_id), (ENV_CLIENT_SECRET, client_secret)) if not value
    ]
    if missing:
        raise PayPalConfigError(f"missing environment variables: {', '.join(missing)}")
    base_url = (source.get(ENV_BASE_URL, "").strip() or SANDBOX_BASE_URL).rstrip("/")
    return PayPalConfig(client_id=client_id, client_secret=client_secret, base_url=base_url)
