"""Web app settings from the environment (T-006, ADR-010)."""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

ENV_SEND_MODE = "DISPUTE_DEFENDER_SEND_MODE"
SendMode = Literal["dry", "live"]

# The app binds to loopback only; there is no option to change it.
HOST = "127.0.0.1"
ALLOWED_HOSTS = ("127.0.0.1", "localhost")
DEFAULT_PORT = 8000


def load_send_mode(env: Mapping[str, str] | None = None) -> SendMode:
    """`live` only when the variable says exactly that (trimmed, any case); anything else is dry."""
    source = os.environ if env is None else env
    return "live" if source.get(ENV_SEND_MODE, "").strip().lower() == "live" else "dry"
