"""Offline test setup. No test may reach PayPal or read real credentials."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import responses

from dispute_defender.paypal import PayPalClient, PayPalConfig

FIXTURES = Path(__file__).parent / "fixtures" / "paypal"
BASE = "https://api-m.sandbox.paypal.com"
DISPUTE_ID = "PP-R-HBV-10197617"
FAKE_CLIENT_ID = "FAKE-CLIENT-ID-for-tests"
FAKE_SECRET = "FAKE-CLIENT-SECRET-for-tests"
FAKE_TOKEN = "FAKE-TEST-TOKEN-not-a-real-token"
FAKE_BUYER_VALUES = ("FAKE-BUYER-NAME", "fake-buyer@example.invalid", "FAKE-BUYER-MESSAGE", "FAKE-BUYER-TXN-0000")


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def _no_real_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def mocked() -> Any:
    """Every HTTP call goes through `responses`; an unregistered URL raises ConnectionError."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def config() -> PayPalConfig:
    return PayPalConfig(client_id=FAKE_CLIENT_ID, client_secret=FAKE_SECRET)


@pytest.fixture
def client(config: PayPalConfig, clock: Clock) -> PayPalClient:
    return PayPalClient(config, clock=clock)


@pytest.fixture
def token_ok(mocked: responses.RequestsMock) -> responses.BaseResponse:
    return mocked.post(f"{BASE}/v1/oauth2/token", json=fixture("token.json"), status=200)
