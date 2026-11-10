from __future__ import annotations

import base64
import json
from decimal import Decimal
from urllib.parse import parse_qs

import pytest
import requests
from responses import matchers

from dispute_defender.paypal import (
    Evidence,
    PayPalAPIError,
    PayPalAuthError,
    PayPalClient,
    PayPalConfigError,
    PayPalNetworkError,
    PayPalResponseError,
    TrackingInfo,
)

from .conftest import (
    BASE,
    DISPUTE_ID,
    FAKE_BUYER_VALUES,
    FAKE_CLIENT_ID,
    FAKE_SECRET,
    FAKE_TOKEN,
    fixture,
)

DISPUTES = f"{BASE}/v1/customer/disputes"
DISPUTE_URL = f"{DISPUTES}/{DISPUTE_ID}"
BEARER = matchers.header_matcher({"Authorization": f"Bearer {FAKE_TOKEN}"})


def assert_safe(text: str) -> None:
    for value in (FAKE_CLIENT_ID, FAKE_SECRET, FAKE_TOKEN, *FAKE_BUYER_VALUES):
        assert value not in text


def evidence() -> Evidence:
    return Evidence(
        tracking_info=[TrackingInfo(carrier_name="FEDEX", tracking_number="122533485")],
        notes="Test evidence with placeholder tracking.",
    )


# --- token ------------------------------------------------------------------


def test_token_request_uses_basic_auth_and_client_credentials(client, mocked, token_ok) -> None:
    token = client.get_token()
    assert token.access_token.get_secret_value() == FAKE_TOKEN
    request = mocked.calls[0].request
    expected = base64.b64encode(f"{FAKE_CLIENT_ID}:{FAKE_SECRET}".encode()).decode()
    assert request.headers["Authorization"] == f"Basic {expected}"
    assert parse_qs(request.body) == {"grant_type": ["client_credentials"]}


def test_token_is_reused_until_near_expiry(client, mocked, token_ok, clock) -> None:
    mocked.get(DISPUTE_URL, json=fixture("dispute_inquiry_waiting.json"))
    client.get_dispute(DISPUTE_ID)
    client.get_dispute(DISPUTE_ID)
    assert token_ok.call_count == 1
    clock.now += 32400 - 60  # inside the refresh margin
    client.get_dispute(DISPUTE_ID)
    assert token_ok.call_count == 2


def test_token_failure_raises_auth_error_without_credentials(client, mocked) -> None:
    mocked.post(f"{BASE}/v1/oauth2/token", json=fixture("error_invalid_client.json"), status=401)
    with pytest.raises(PayPalAuthError) as info:
        client.list_disputes()
    assert info.value.http_status == 401
    assert info.value.name == "invalid_client"
    assert_safe(str(info.value))


def test_token_error_body_echoing_secret_is_redacted(client, mocked) -> None:
    mocked.post(
        f"{BASE}/v1/oauth2/token",
        json={"name": f"bad {FAKE_SECRET}", "debug_id": FAKE_CLIENT_ID},
        status=401,
    )
    with pytest.raises(PayPalAuthError) as info:
        client.get_token()
    assert_safe(str(info.value))


def test_token_response_without_access_token_is_rejected(client, mocked) -> None:
    mocked.post(f"{BASE}/v1/oauth2/token", json={"expires_in": 100}, status=200)
    with pytest.raises(PayPalResponseError, match="access_token"):
        client.get_token()


def test_from_env_reads_environment(monkeypatch, mocked) -> None:
    with pytest.raises(PayPalConfigError, match="PAYPAL_CLIENT_ID"):
        PayPalClient.from_env()
    monkeypatch.setenv("PAYPAL_CLIENT_ID", FAKE_CLIENT_ID)
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", FAKE_SECRET)
    assert isinstance(PayPalClient.from_env(), PayPalClient)


# --- reads ------------------------------------------------------------------


def test_list_disputes_empty(client, mocked, token_ok) -> None:
    mocked.get(
        DISPUTES, json=fixture("dispute_list_empty.json"),
        match=[BEARER, matchers.query_param_matcher({"page_size": "20"})],
    )
    assert client.list_disputes() == []


def test_list_disputes_one(client, mocked, token_ok) -> None:
    mocked.get(DISPUTES, json=fixture("dispute_list_one.json"), match=[BEARER])
    items = client.list_disputes()
    assert [(i.dispute_id, i.status, i.stage) for i in items] == [
        (DISPUTE_ID, "WAITING_FOR_SELLER_RESPONSE", "INQUIRY")
    ]


@pytest.mark.parametrize("size", [0, 51])
def test_list_disputes_rejects_bad_page_size(client, size) -> None:
    with pytest.raises(ValueError):
        client.list_disputes(page_size=size)


def test_get_dispute(client, mocked, token_ok) -> None:
    mocked.get(DISPUTE_URL, json=fixture("dispute_inquiry_waiting.json"), match=[BEARER])
    dispute = client.get_dispute(DISPUTE_ID)
    assert dispute.status == "WAITING_FOR_SELLER_RESPONSE"
    assert dispute.amount.value == Decimal("10.00")
    assert dispute.has_link("send-message")
    assert_safe(repr(dispute.model_dump()))


def test_get_dispute_raw_returns_unvalidated_json(client, mocked, token_ok) -> None:
    mocked.get(DISPUTE_URL, json=fixture("dispute_inquiry_waiting.json"))
    raw = client.get_dispute_raw(DISPUTE_ID)
    assert "disputed_transactions" in raw


@pytest.mark.parametrize("bad_id", ["../x", "PP-R/1", "", "a" * 65, "id?x=1", "id#x"])
def test_invalid_dispute_id_is_rejected_before_any_http(client, mocked, bad_id) -> None:
    with pytest.raises(ValueError):
        client.get_dispute(bad_id)
    with pytest.raises(ValueError):
        client.send_message(bad_id, "hello")
    assert len(mocked.calls) == 0


# --- actions ----------------------------------------------------------------


def test_send_message_sends_json(client, mocked, token_ok) -> None:
    mocked.post(
        f"{DISPUTE_URL}/send-message",
        json=fixture("action_ack.json"),
        match=[BEARER, matchers.json_params_matcher({"message": "Hello from the seller."})],
    )
    ack = client.send_message(DISPUTE_ID, "Hello from the seller.")
    assert ack.has_link("self")


@pytest.mark.parametrize("message", ["", "   "])
def test_send_message_rejects_empty(client, mocked, message) -> None:
    with pytest.raises(ValueError):
        client.send_message(DISPUTE_ID, message)
    assert len(mocked.calls) == 0


def test_provide_evidence_sends_multipart_input_part(client, mocked, token_ok) -> None:
    mocked.post(f"{DISPUTE_URL}/provide-evidence", json=fixture("action_ack.json"), match=[BEARER])
    client.provide_evidence(DISPUTE_ID, [evidence()])
    request = mocked.calls[-1].request
    assert request.headers["Content-Type"].startswith("multipart/form-data")
    body = request.body.decode() if isinstance(request.body, bytes) else request.body
    assert 'name="input"' in body
    assert "Content-Type: application/json" in body
    part = body.split("Content-Type: application/json", 1)[1].split("\r\n\r\n", 1)[1].split("\r\n--", 1)[0]
    assert json.loads(part) == {"evidences": [evidence().to_payload()]}


def test_provide_evidence_accepts_empty_success_body(client, mocked, token_ok) -> None:
    mocked.post(f"{DISPUTE_URL}/provide-evidence", body="", status=200)
    assert client.provide_evidence(DISPUTE_ID, [evidence()]).links == []


@pytest.mark.parametrize("value", [[], ["not evidence"]])
def test_provide_evidence_rejects_bad_input(client, mocked, value) -> None:
    with pytest.raises(ValueError):
        client.provide_evidence(DISPUTE_ID, value)
    assert len(mocked.calls) == 0


# --- errors -----------------------------------------------------------------


def test_action_not_allowed_raises_api_error_with_issue_and_debug_id(client, mocked, token_ok) -> None:
    mocked.post(f"{DISPUTE_URL}/send-message", json=fixture("error_action_not_allowed.json"), status=400)
    with pytest.raises(PayPalAPIError) as info:
        client.send_message(DISPUTE_ID, "hello")
    error = info.value
    assert not isinstance(error, PayPalAuthError)
    assert error.http_status == 400
    assert error.name == "INVALID_REQUEST"
    assert error.issues == ["ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE"]
    assert error.debug_id == "f41195223259c"
    assert "ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE" in str(error)
    assert "f41195223259c" in str(error)
    assert_safe(str(error))  # the fixture's description echoes a fake buyer name


def test_error_with_non_json_body(client, mocked, token_ok) -> None:
    mocked.get(DISPUTE_URL, body="<html>oops</html>", status=500)
    with pytest.raises(PayPalAPIError) as info:
        client.get_dispute(DISPUTE_ID)
    assert info.value.http_status == 500
    assert info.value.issues == [] and info.value.debug_id is None


def test_success_with_non_json_body(client, mocked, token_ok) -> None:
    mocked.get(DISPUTE_URL, body="<html>oops</html>", status=200)
    with pytest.raises(PayPalResponseError, match="not JSON"):
        client.get_dispute(DISPUTE_ID)


def test_success_with_json_that_is_not_an_object(client, mocked, token_ok) -> None:
    mocked.get(DISPUTE_URL, json=[1, 2], status=200)
    with pytest.raises(PayPalResponseError, match="not a JSON object"):
        client.get_dispute(DISPUTE_ID)


def test_malformed_dispute_names_fields_not_values(client, mocked, token_ok) -> None:
    body = fixture("dispute_inquiry_waiting.json")
    del body["status"]
    body["dispute_amount"]["value"] = "FAKE-BUYER-NAME"
    mocked.get(DISPUTE_URL, json=body)
    with pytest.raises(PayPalResponseError) as info:
        client.get_dispute(DISPUTE_ID)
    assert "status" in str(info.value) and "dispute_amount.value" in str(info.value)
    assert_safe(str(info.value))


def test_network_error(client, mocked, token_ok) -> None:
    mocked.get(DISPUTE_URL, body=requests.ConnectionError(f"boom {FAKE_TOKEN}"))
    with pytest.raises(PayPalNetworkError) as info:
        client.get_dispute(DISPUTE_ID)
    assert "ConnectionError" in str(info.value)
    assert_safe(str(info.value))


def test_redirect_is_not_followed(client, mocked, token_ok) -> None:
    mocked.get(DISPUTE_URL, status=302, headers={"Location": "https://example.com/elsewhere"})
    with pytest.raises(PayPalNetworkError, match="redirect"):
        client.get_dispute(DISPUTE_ID)
    assert all("example.com" not in call.request.url for call in mocked.calls)


def test_unregistered_url_never_reaches_network(client, mocked) -> None:
    # Guard for the test setup itself: with no mock registered, the call fails offline.
    with pytest.raises(PayPalNetworkError):
        client.get_token()


def test_401_on_api_call_is_not_retried(client, mocked, token_ok) -> None:
    unauthorized = mocked.get(DISPUTE_URL, json={"name": "AUTHENTICATION_FAILURE", "debug_id": "x1"}, status=401)
    with pytest.raises(PayPalAPIError) as info:
        client.get_dispute(DISPUTE_ID)
    assert info.value.http_status == 401
    assert unauthorized.call_count == 1 and token_ok.call_count == 1
