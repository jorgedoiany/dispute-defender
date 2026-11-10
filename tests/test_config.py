from __future__ import annotations

import pytest

from dispute_defender.paypal import SANDBOX_BASE_URL, PayPalConfig, PayPalConfigError, load_config

from .conftest import FAKE_CLIENT_ID, FAKE_SECRET

VALID = {"PAYPAL_CLIENT_ID": FAKE_CLIENT_ID, "PAYPAL_CLIENT_SECRET": FAKE_SECRET}


def test_loads_from_env_mapping_with_sandbox_default() -> None:
    config = load_config(VALID)
    assert config.client_id == FAKE_CLIENT_ID
    assert config.client_secret == FAKE_SECRET
    assert config.base_url == SANDBOX_BASE_URL


def test_loads_from_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in VALID.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PAYPAL_BASE_URL", SANDBOX_BASE_URL + "/")
    assert load_config().base_url == SANDBOX_BASE_URL


@pytest.mark.parametrize("missing", ["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET"])
def test_missing_variable_is_named_without_values(missing: str) -> None:
    env = {k: v for k, v in VALID.items() if k != missing}
    with pytest.raises(PayPalConfigError) as info:
        load_config(env)
    assert missing in str(info.value)
    assert FAKE_SECRET not in str(info.value)
    assert FAKE_CLIENT_ID not in str(info.value)


def test_blank_values_count_as_missing() -> None:
    with pytest.raises(PayPalConfigError, match="PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET"):
        load_config({"PAYPAL_CLIENT_ID": "  ", "PAYPAL_CLIENT_SECRET": ""})


@pytest.mark.parametrize(
    "url",
    [
        "https://api-m.paypal.com",
        "http://api-m.sandbox.paypal.com",
        "https://api-m.sandbox.paypal.com/v1",
        "https://api-m.sandbox.paypal.com.evil.example",
        "https://api-m.sandbox.paypal.com:8443",
        "https://user:pw@api-m.sandbox.paypal.com",
        "https://example.com",
    ],
)
def test_non_sandbox_base_url_is_refused(url: str) -> None:
    with pytest.raises(PayPalConfigError, match="must be https://api-m.sandbox.paypal.com"):
        load_config({**VALID, "PAYPAL_BASE_URL": url})
    with pytest.raises(PayPalConfigError):
        PayPalConfig(client_id=FAKE_CLIENT_ID, client_secret=FAKE_SECRET, base_url=url)


def test_repr_hides_credentials() -> None:
    text = repr(load_config(VALID))
    assert FAKE_SECRET not in text
    assert FAKE_CLIENT_ID not in text
