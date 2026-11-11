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


AWS_ENV = (
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE", "AWS_DEFAULT_PROFILE",
    "AWS_REGION", "AWS_DEFAULT_REGION", "BEDROCK_MODEL_ID", "BEDROCK_MODEL_ID_SECONDARY",
)


@pytest.fixture(autouse=True)
def _no_real_aws(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No test may read the real AWS profile or reach AWS. botocore sends through urllib3,
    which `responses` does not cover, so its HTTP send is blocked here as well."""
    for name in AWS_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-aws-credentials"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")

    def blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("network access to AWS is disabled in tests")

    monkeypatch.setattr("botocore.httpsession.URLLib3Session.send", blocked)


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
