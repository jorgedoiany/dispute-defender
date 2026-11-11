"""Offline tests for the approval page (T-006, ADR-010).

PayPal is the real PayPalClient against `responses` mocks (conftest); the model is a
fake client with scripted responses. Nothing reaches the network. Each section maps to
a row of the T-006 acceptance table in the plan / ADR-010.
"""
from __future__ import annotations

import html
import logging
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import requests
import responses
from fastapi.testclient import TestClient
from markupsafe import escape

from dispute_defender.drafter import TOOL_NAME, ModelRequest, ModelResponse, ToolUse
from dispute_defender.paypal import PayPalClient
from dispute_defender.web import CsrfTokens, create_app, load_send_mode
from dispute_defender.web import __main__ as web_main
from dispute_defender.web.csrf import TTL_SECONDS

from .conftest import BASE, DISPUTE_ID, FAKE_BUYER_VALUES, FAKE_CLIENT_ID, FAKE_SECRET, FAKE_TOKEN, fixture

MODEL = "us.anthropic.claude-sonnet-4-6"
TXN_ID = "54X87564PT289050U"
DISPUTE_URL = f"{BASE}/v1/customer/disputes/{DISPUTE_ID}"
EVIDENCE_URL = f"{DISPUTE_URL}/provide-evidence"
LIST_URL = f"{BASE}/v1/customer/disputes"
FORM = {"tracking": "122533485", "carrier": "FEDEX"}
DRY_BANNER = "DRY RUN: nothing will be sent"
LIVE_BANNER = "LIVE SANDBOX SEND"
FIXED_NOW = datetime(2026, 11, 10, 18, 30, 5, tzinfo=timezone.utc)
READ_AT = "2026-11-10 18:30:05 UTC"


# --- fakes and helpers -------------------------------------------------------


def c(type_: str, value: Any, source: str | None = None) -> dict[str, Any]:
    sources = {"tracking_number": "merchant_record", "carrier": "merchant_record"}
    return {"type": type_, "source": source or sources.get(type_, "paypal"), "value": value}


GOOD = [
    c("transaction_id", TXN_ID),
    c("amount", {"value": "10.00", "currency_code": "USD"}),
    c("transaction_date", "2026-11-09"),
    c("seller_protection", True),
    c("tracking_number", "122533485"),
    c("carrier", "FedEx"),
]
GOOD_NOTES = (
    f"The disputed payment is PayPal transaction {TXN_ID}. The transaction amount was 10.00 USD. "
    "The transaction was made on 2026-11-09 (UTC). PayPal lists this transaction as eligible for "
    "Seller Protection. According to our records, the order was shipped with FEDEX, tracking number 122533485."
)


def reply(claims: list[dict[str, Any]]) -> ModelResponse:
    return ModelResponse(stop_reason="tool_use", tool_uses=(ToolUse(name=TOOL_NAME, input={"claims": claims}),),
                         input_tokens=100, output_tokens=20, request_id="req-1")


class FakeModel:
    def __init__(self, *responses_: ModelResponse | Exception) -> None:
        self.responses = list(responses_)
        self.requests: list[ModelRequest] = []

    def converse(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


class Harness:
    def __init__(self, mocked: responses.RequestsMock, send_mode: str, model: FakeModel) -> None:
        self.mocked = mocked
        self.model = model
        self.clock = Clock()
        self.csrf = CsrfTokens(b"t" * 32, clock=self.clock)
        paypal = PayPalClient(_config())
        self.app = create_app(paypal=paypal, model_client=model, model_id=MODEL, send_mode=send_mode,
                              csrf=self.csrf, now=lambda: FIXED_NOW)
        self.client = TestClient(self.app, base_url="http://127.0.0.1")

    # PayPal mocks
    def dispute(self, body: dict[str, Any] | None = None, status: int = 200) -> None:
        self.mocked.get(DISPUTE_URL, json=body if body is not None else sendable(), status=status)

    def ack(self, status: int = 200, body: dict[str, Any] | None = None) -> None:
        self.mocked.post(EVIDENCE_URL, json=body if body is not None else fixture("action_ack.json"), status=status)

    # call log
    def calls(self, method: str | None = None, url: str | None = None) -> list[Any]:
        return [call for call in self.mocked.calls
                if (method is None or call.request.method == method)
                and (url is None or call.request.url.split("?")[0] == url)]

    def evidence_posts(self) -> list[Any]:
        return self.calls("POST", EVIDENCE_URL)

    # page flow
    def draft(self, **form: str) -> Any:
        """POST the draft form with a valid token (one PayPal GET, one model call).
        The dispute page itself, and taking the token from it, are covered by the dry-run flow test."""
        data = {**FORM, "csrf": self.csrf.issue(DISPUTE_ID, "draft"), **form}
        return self.client.post(f"/disputes/{DISPUTE_ID}/draft", data=data)

    def approve(self, draft_page: Any, **extra: str) -> Any:
        data = approve_form(draft_page.text)
        data.update(extra)
        return self.client.post(f"/disputes/{DISPUTE_ID}/approve", data=data)

    def approve_direct(self, shown_hash: str = "0" * 64, **extra: str) -> Any:
        data = {**FORM, "csrf": self.csrf.issue(DISPUTE_ID, "approve"), "shown_hash": shown_hash, **extra}
        return self.client.post(f"/disputes/{DISPUTE_ID}/approve", data=data)


def _config() -> Any:
    from dispute_defender.paypal import PayPalConfig
    return PayPalConfig(client_id=FAKE_CLIENT_ID, client_secret=FAKE_SECRET)


def sendable(**changes: Any) -> dict[str, Any]:
    body = fixture("dispute_inquiry_waiting.json")
    body.update(changes)
    return body


def not_sendable() -> dict[str, Any]:
    return fixture("dispute_under_review.json")


def read_back(status: str = "WAITING_FOR_BUYER_RESPONSE") -> dict[str, Any]:
    """A read-back that differs from the pre-send state and from the ack's links."""
    body = sendable(status=status)
    body["links"] = [link for link in body["links"] if link["rel"] in ("self", "accept_claim")]
    return body


def hidden(page: str, name: str, form_action: str | None = None) -> str:
    scope = page
    if form_action is not None:
        start = page.index(f'action="{form_action}"')
        scope = page[start:page.index("</form>", start)]
    match = re.search(rf'name="{name}" value="([^"]*)"', scope)
    assert match, f"no hidden input {name}"
    return html.unescape(match.group(1))


def approve_form(page: str) -> dict[str, str]:
    action = f"/disputes/{DISPUTE_ID}/approve"
    assert f'action="{action}"' in page, "no approve form on the page"
    return {name: hidden(page, name, action) for name in ("csrf", "tracking", "carrier", "shown_hash")}


@pytest.fixture
def make(mocked: responses.RequestsMock, token_ok: Any) -> Iterator[Any]:
    def build(*model_responses: ModelResponse | Exception, send_mode: str = "dry") -> Harness:
        return Harness(mocked, send_mode, FakeModel(*model_responses))
    yield build


# --- Row: the page shows the dispute, each claim with verdict and reason, Approve / Reject ---


def test_index_lists_disputes(make: Any) -> None:
    h = make()
    h.mocked.get(LIST_URL, json=fixture("dispute_list_one.json"))
    page = h.client.get("/")
    assert page.status_code == 200
    assert DISPUTE_ID in page.text and "WAITING_FOR_SELLER_RESPONSE" in page.text
    assert f'href="/disputes/{DISPUTE_ID}"' in page.text


def test_dispute_page_shows_facts_and_draft_form(make: Any) -> None:
    h = make()
    h.dispute()
    page = h.client.get(f"/disputes/{DISPUTE_ID}")
    assert page.status_code == 200
    for text in ("WAITING_FOR_SELLER_RESPONSE", "INQUIRY", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "10.00 USD",
                 TXN_ID, "2026-11-09", "provide-evidence", "offers provide-evidence", READ_AT):
        assert text in page.text
    assert "1 (text not shown)" in page.text  # buyer message count only
    assert f'action="/disputes/{DISPUTE_ID}/draft"' in page.text
    assert '<option value="FEDEX">' in page.text and "UPS" not in page.text
    assert h.model.requests == []


def test_dispute_page_shows_response_options_for_information(make: Any) -> None:
    h = make()
    h.dispute(sendable(allowed_response_options={"accept_claim": {}, "make_offer": {}}))
    page = h.client.get(f"/disputes/{DISPUTE_ID}")
    assert "accept_claim, make_offer" in page.text


def test_draft_page_shows_each_claim_with_verdict_reason_and_approve_reject(make: Any) -> None:
    claims = GOOD + [c("amount", {"value": "12.00", "currency_code": "USD"})]
    h = make(reply(claims))
    h.dispute()
    page = h.draft()
    assert page.status_code == 200, page.text
    text = page.text
    assert text.count('class="VERIFIED"') == 6
    assert text.count('class="BLOCKED"') == 1
    assert "verified against PayPal transaction data" in text
    assert "verified against merchant record" in text
    assert "contradicts PayPal transaction data" in text
    assert html.escape(GOOD_NOTES) in text
    assert "Approve (dry run)" in text
    assert f'href="/disputes/{DISPUTE_ID}">Reject' in text
    assert len(h.model.requests) == 1
    assert h.evidence_posts() == []


def test_flagged_claim_is_shown_with_its_reason_and_left_out_of_the_text(make: Any) -> None:
    body = sendable()
    del body["disputed_transactions"][0]["seller_protection_eligible"]
    h = make(reply(GOOD))
    h.dispute(body)
    page = h.draft()
    assert page.text.count('class="FLAGGED"') == 1
    assert "no seller_protection_eligible" in page.text
    assert "Seller Protection" not in page.text.split("Response text")[1].split("</div>")[0]
    assert f'action="/disputes/{DISPUTE_ID}/approve"' in page.text  # other claims can still be sent


def test_reject_is_a_plain_link_that_sends_nothing(make: Any) -> None:
    h = make(reply(GOOD))
    h.dispute()
    h.draft()
    h.client.get(f"/disputes/{DISPUTE_ID}")
    assert h.evidence_posts() == [] and h.calls("POST", None) == h.calls("POST", f"{BASE}/v1/oauth2/token")


# --- Row: approving sends in the sandbox and shows the new state --------------
# --- Row: the state is read back, never assumed ------------------------------


def test_live_approve_sends_exactly_once_then_reads_back(make: Any) -> None:
    h = make(reply(GOOD), reply(GOOD), send_mode="live")
    h.dispute()  # draft read
    h.dispute()  # approve read
    h.dispute(read_back())  # read-back after the POST
    h.ack()
    draft_page = h.draft()
    assert "Approve and send (live sandbox)" in draft_page.text
    result = h.approve(draft_page)
    assert result.status_code == 200, result.text
    posts = h.evidence_posts()
    assert len(posts) == 1
    body = posts[0].request.body
    body = body.decode() if isinstance(body, bytes) else body
    assert '"carrier_name": "FEDEX"' in body and '"tracking_number": "122533485"' in body
    assert GOOD_NOTES in body
    # order: GET (approve), POST, GET (read-back)
    methods = [(call.request.method, call.request.url.split("?")[0]) for call in h.mocked.calls]
    post_index = methods.index(("POST", EVIDENCE_URL))
    assert methods[post_index + 1] == ("GET", DISPUTE_URL)
    assert "Sent to the PayPal sandbox" in result.text
    assert len(h.model.requests) == 2


def test_result_page_shows_the_read_back_state_not_an_assumed_one(make: Any) -> None:
    h = make(reply(GOOD), reply(GOOD), send_mode="live")
    h.dispute()
    h.dispute()
    h.dispute(read_back("WAITING_FOR_BUYER_RESPONSE"))
    h.ack()  # ack links: self only
    result = h.approve(h.draft())
    readback = result.text[result.text.index("Dispute state read back from PayPal"):]
    assert f"Read back from PayPal at {READ_AT}" in readback
    assert "WAITING_FOR_BUYER_RESPONSE" in readback
    assert "accept-claim, self" in readback  # links from the read-back, not from the ack
    assert "<td>UNDER_REVIEW</td>" not in readback  # nothing assumed
    assert "Before approving: WAITING_FOR_SELLER_RESPONSE / INQUIRY" in result.text
    assert "not changed by this run" not in result.text
    assert f'href="/disputes/{DISPUTE_ID}/state"' in result.text


def test_failed_read_back_still_says_the_evidence_was_sent(make: Any) -> None:
    h = make(reply(GOOD), reply(GOOD), send_mode="live")
    h.dispute()
    h.dispute()
    h.dispute(fixture("error_action_not_allowed.json"), status=500)
    h.ack()
    result = h.approve(h.draft())
    assert result.status_code == 200
    assert len(h.evidence_posts()) == 1
    assert "the evidence WAS sent" in result.text and "HTTP 500" in result.text


def test_state_route_reads_back_with_time(make: Any) -> None:
    h = make()
    h.dispute(read_back("UNDER_REVIEW"))
    page = h.client.get(f"/disputes/{DISPUTE_ID}/state")
    assert page.status_code == 200
    assert f"Read back from PayPal at {READ_AT}" in page.text and "UNDER_REVIEW" in page.text
    assert len(h.calls("GET", DISPUTE_URL)) == 1


# --- Row: BLOCKED claims cannot be sent; the server re-verifies and ignores browser verdicts ---


def test_blocked_claim_at_approve_is_not_sent_even_if_the_form_says_verified(make: Any) -> None:
    blocked = [cl if cl["type"] != "tracking_number" else c("tracking_number", "999") for cl in GOOD]
    h = make(reply(GOOD), reply(blocked), send_mode="live")
    h.dispute()
    h.dispute()
    h.ack()
    page = h.approve(h.draft(), verdict="VERIFIED", tracking_verdict="VERIFIED",
                     notes="EVIL-NOTES", evidence='{"tracking_number": "999"}')
    assert page.status_code == 409
    assert h.evidence_posts() == []
    assert "Nothing was sent" in page.text and 'class="BLOCKED"' in page.text


def test_form_tracking_that_differs_from_the_verified_one_is_not_sent(make: Any) -> None:
    h = make(reply(GOOD), reply(GOOD), send_mode="live")
    h.dispute()
    h.dispute()
    h.ack()
    form = approve_form(h.draft().text)
    form["tracking"] = "555000555"  # the merchant record now disagrees with the model's claim
    page = h.client.post(f"/disputes/{DISPUTE_ID}/approve", data=form)
    assert page.status_code == 409
    assert h.evidence_posts() == []
    assert "contradicts merchant record" in page.text


def test_blocked_and_flagged_values_and_extra_fields_never_reach_the_post_body(make: Any) -> None:
    extra = [c("amount", {"value": "999.99", "currency_code": "EUR"}),
             c("transaction_date", "2020-01-01")]
    h = make(reply(GOOD + extra), reply(GOOD + extra), send_mode="live")
    h.dispute()
    h.dispute()
    h.dispute(read_back())
    h.ack()
    draft_page = h.draft()
    assert draft_page.text.count('class="BLOCKED"') == 2
    result = h.approve(draft_page, notes="EVIL-NOTES", verdict="VERIFIED", carrier_name="UPS")
    assert result.status_code == 200, result.text
    (post,) = h.evidence_posts()
    body = post.request.body
    body = body.decode() if isinstance(body, bytes) else body
    for leaked in ("999.99", "EUR", "2020-01-01", "EVIL-NOTES", "UPS"):
        assert leaked not in body


# --- Row: refused when the dispute does not offer the action -----------------


def test_approve_refused_before_any_model_call_when_link_absent(make: Any) -> None:
    h = make(reply(GOOD), send_mode="live")
    h.dispute(not_sendable())
    page = h.approve_direct()
    assert page.status_code == 409
    assert "does not offer provide-evidence" in page.text and "UNDER_REVIEW" in page.text
    assert h.model.requests == []
    assert h.evidence_posts() == []


def test_draft_refused_before_any_model_call_when_link_absent(make: Any) -> None:
    h = make(reply(GOOD))
    h.dispute(not_sendable())
    h.dispute(not_sendable())
    page = h.client.get(f"/disputes/{DISPUTE_ID}")
    assert "Cannot respond now" in page.text and "/draft" not in page.text
    token = h.csrf.issue(DISPUTE_ID, "draft")
    page = h.client.post(f"/disputes/{DISPUTE_ID}/draft", data={**FORM, "csrf": token})
    assert page.status_code == 409 and "does not offer provide-evidence" in page.text
    assert h.model.requests == []


def test_response_options_never_gate_the_send(make: Any) -> None:
    h = make(reply(GOOD), reply(GOOD), send_mode="live")
    with_options = sendable(allowed_response_options={"accept_claim": {}})
    h.dispute(with_options)
    h.dispute(with_options)
    h.dispute(read_back())
    h.ack()
    assert h.approve(h.draft()).status_code == 200
    assert len(h.evidence_posts()) == 1


# --- Row: nothing is sent when no claim is VERIFIED --------------------------


def test_nothing_verified_means_no_approve_form_and_no_send(make: Any) -> None:
    bad = [c("amount", {"value": "12.00", "currency_code": "USD"}), c("tracking_number", "000"), c("carrier", "FedEx")]
    only_bad = bad[:2]
    h = make(reply(only_bad), reply(only_bad), send_mode="live")
    h.dispute()
    h.dispute()
    h.ack()
    page = h.draft()
    assert "No response text" in page.text and "Cannot send" in page.text
    assert f'action="/disputes/{DISPUTE_ID}/approve"' not in page.text
    forced = h.approve_direct()  # a forged approve with a valid token still sends nothing
    assert forced.status_code == 409
    assert h.evidence_posts() == []


# --- Row: the text changed between draft and approve -------------------------


def test_changed_text_between_draft_and_approve_is_not_sent_and_the_new_draft_is_shown(make: Any) -> None:
    without_amount = [cl for cl in GOOD if cl["type"] != "amount"]
    h = make(reply(GOOD), reply(without_amount), send_mode="live")
    h.dispute()
    h.dispute()
    h.ack()
    first = h.draft()
    page = h.approve(first)
    assert page.status_code == 409
    assert h.evidence_posts() == []
    assert "differs from the one shown" in page.text
    assert "10.00 USD." not in page.text.split("Response text")[1].split("</div>")[0]
    new_form = approve_form(page.text)  # the merchant can approve the new text
    assert new_form["shown_hash"] != approve_form(first.text)["shown_hash"]


# --- Row: dry run sends nothing ----------------------------------------------


def test_dry_run_runs_every_step_but_sends_nothing(make: Any) -> None:
    h = make(reply(GOOD), reply(GOOD))
    h.mocked.get(LIST_URL, json=fixture("dispute_list_one.json"))
    h.dispute()  # dispute page
    h.dispute()  # draft
    h.dispute()  # approve
    h.dispute(read_back())  # read-back
    h.dispute(read_back())  # state
    pages = [h.client.get("/")]
    pages.append(h.client.get(f"/disputes/{DISPUTE_ID}"))
    token = hidden(pages[-1].text, "csrf")
    pages.append(h.client.post(f"/disputes/{DISPUTE_ID}/draft", data={**FORM, "csrf": token}))
    pages.append(h.approve(pages[-1]))
    pages.append(h.client.get(f"/disputes/{DISPUTE_ID}/state"))
    pages.append(h.client.post(f"/disputes/{DISPUTE_ID}/approve", data={}))  # an error page
    assert [p.status_code for p in pages] == [200, 200, 200, 200, 200, 403]
    for p in pages:
        assert DRY_BANNER in p.text and LIVE_BANNER not in p.text
    result = pages[3].text
    assert "Dry run: nothing was sent" in result
    assert "not changed by this run" in result
    assert "Approve (dry run)" in pages[2].text
    assert h.calls("POST", EVIDENCE_URL) == []
    assert [call.request.method for call in h.mocked.calls if "disputes" in call.request.url] == ["GET"] * 6
    assert len(h.model.requests) == 2


def test_live_banner_on_every_page(make: Any) -> None:
    h = make(send_mode="live")
    h.mocked.get(LIST_URL, json=fixture("dispute_list_one.json"))
    for page in (h.client.get("/"), h.client.post(f"/disputes/{DISPUTE_ID}/draft", data={})):
        assert LIVE_BANNER in page.text and DRY_BANNER not in page.text


@pytest.mark.parametrize(("value", "mode"), [
    (None, "dry"), ("", "dry"), ("dry", "dry"), ("live", "live"), (" LIVE ", "live"),
    ("yes", "dry"), ("true", "dry"), ("live-ish", "dry"), ("1", "dry"),
])
def test_send_mode_is_dry_unless_exactly_live(value: str | None, mode: str) -> None:
    env = {} if value is None else {"DISPUTE_DEFENDER_SEND_MODE": value}
    assert load_send_mode(env) == mode


# --- Row: HTML escaping ------------------------------------------------------


def test_hostile_values_are_escaped_and_bidi_removed(make: Any) -> None:
    script = "<script>alert(1)</script>"
    img = '"><img src=x onerror=alert(1)>'
    hostile = [c("transaction_id", img + "‮" + "X"), c("carrier", script)]
    h = make(reply(hostile))
    body = sendable(reason=script)
    h.dispute(body)
    h.dispute(body)
    dispute_page = h.client.get(f"/disputes/{DISPUTE_ID}")
    page = h.client.post(f"/disputes/{DISPUTE_ID}/draft",
                         data={**FORM, "csrf": hidden(dispute_page.text, "csrf")})
    for text in (dispute_page.text, page.text):
        assert script not in text and "<img" not in text
        assert html.escape(script) in text
    assert "‮" not in page.text
    assert str(escape(img)) + "X" in page.text


def test_long_claim_values_are_cut(make: Any) -> None:
    h = make(reply([c("transaction_id", "A" * 5000)]))
    h.dispute()
    page = h.draft()
    assert "<td>" + "A" * 200 + " [cut]</td>" in page.text  # the value cell
    assert "A" * 300 not in page.text  # the reason, which repeats the value, is cut too


# --- Row: CSRF and host checks -----------------------------------------------


def _assert_nothing_called(h: Harness) -> None:
    assert h.model.requests == []
    assert [call for call in h.mocked.calls if "disputes" in call.request.url] == []


@pytest.mark.parametrize("route", ["draft", "approve"])
def test_missing_csrf_token_is_403(make: Any, route: str) -> None:
    h = make(reply(GOOD), send_mode="live")
    page = h.client.post(f"/disputes/{DISPUTE_ID}/{route}", data={**FORM, "shown_hash": "0" * 64})
    assert page.status_code == 403 and "Nothing was sent" in page.text
    _assert_nothing_called(h)


def test_forged_csrf_token_is_403(make: Any) -> None:
    h = make(reply(GOOD), send_mode="live")
    forged = CsrfTokens(b"attacker-key-attacker-key-attack").issue(DISPUTE_ID, "approve")
    page = h.approve_direct(csrf=forged)
    assert page.status_code == 403
    _assert_nothing_called(h)


def test_expired_csrf_token_is_403(make: Any) -> None:
    h = make(reply(GOOD), send_mode="live")
    token = h.csrf.issue(DISPUTE_ID, "approve")
    h.clock.now += TTL_SECONDS + 1
    page = h.approve_direct(csrf=token)
    assert page.status_code == 403
    _assert_nothing_called(h)


def test_reused_csrf_token_is_403_so_a_resubmit_cannot_send_twice(make: Any) -> None:
    h = make(reply(GOOD), reply(GOOD), reply(GOOD), send_mode="live")
    h.dispute()
    h.dispute()
    h.dispute(read_back())
    h.ack()
    form = approve_form(h.draft().text)
    assert h.client.post(f"/disputes/{DISPUTE_ID}/approve", data=form).status_code == 200
    again = h.client.post(f"/disputes/{DISPUTE_ID}/approve", data=form)
    assert again.status_code == 403
    assert len(h.evidence_posts()) == 1
    assert len(h.model.requests) == 2


def test_csrf_token_for_another_dispute_is_403(make: Any) -> None:
    h = make(reply(GOOD), send_mode="live")
    token = h.csrf.issue("PP-R-KXL-10197854", "approve")
    assert h.approve_direct(csrf=token).status_code == 403
    _assert_nothing_called(h)


def test_draft_token_cannot_approve(make: Any) -> None:
    h = make(reply(GOOD), send_mode="live")
    assert h.approve_direct(csrf=h.csrf.issue(DISPUTE_ID, "draft")).status_code == 403
    _assert_nothing_called(h)


def test_cross_origin_post_is_403(make: Any) -> None:
    h = make(reply(GOOD), send_mode="live")
    data = {**FORM, "csrf": h.csrf.issue(DISPUTE_ID, "approve"), "shown_hash": "0" * 64}
    page = h.client.post(f"/disputes/{DISPUTE_ID}/approve", data=data, headers={"Origin": "http://evil.example"})
    assert page.status_code == 403 and "Cross-origin" in page.text
    _assert_nothing_called(h)


def test_same_origin_post_is_allowed(make: Any) -> None:
    h = make(reply(GOOD))
    h.dispute()
    token = h.csrf.issue(DISPUTE_ID, "draft")
    page = h.client.post(f"/disputes/{DISPUTE_ID}/draft", data={**FORM, "csrf": token},
                         headers={"Origin": "http://127.0.0.1"})
    assert page.status_code == 200


def _browser_post(h: Harness, origin: str | None, *, page_origin: str = "http://127.0.0.1:8000") -> Any:
    """A form POST as Chrome sends it from a page served at `page_origin` (exact headers)."""
    client = TestClient(h.app, base_url=page_origin)
    host = page_origin.split("://", 1)[1]
    headers = {
        "Host": host,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": f"{page_origin}/disputes/{DISPUTE_ID}",
        "Sec-Fetch-Site": "same-origin" if origin == page_origin else "cross-site",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
    }
    if origin is not None:
        headers["Origin"] = origin
    data = {**FORM, "csrf": h.csrf.issue(DISPUTE_ID, "draft")}
    return client.post(f"/disputes/{DISPUTE_ID}/draft", data=data, headers=headers)


def test_referrer_policy_lets_browsers_send_the_real_origin_on_our_own_posts(make: Any) -> None:
    # "no-referrer" made Chrome send `Origin: null` on same-origin form posts, which the
    # Origin check refused (bug found in a real browser). "same-origin" keeps the origin.
    h = make()
    h.mocked.get(LIST_URL, json=fixture("dispute_list_empty.json"))
    assert h.client.get("/").headers["referrer-policy"] == "same-origin"


@pytest.mark.parametrize("page_origin", ["http://127.0.0.1:8000", "http://localhost:8000", "http://127.0.0.1:8123"])
def test_same_origin_browser_form_post_is_accepted(make: Any, page_origin: str) -> None:
    h = make(reply(GOOD))
    h.dispute()
    page = _browser_post(h, page_origin, page_origin=page_origin)
    assert page.status_code == 200, page.text
    assert "Draft for" in page.text and len(h.model.requests) == 1


def test_browser_post_without_origin_still_needs_the_token(make: Any) -> None:
    h = make(reply(GOOD))
    h.dispute()
    assert _browser_post(h, None).status_code == 200
    client = TestClient(h.app, base_url="http://127.0.0.1:8000")
    page = client.post(f"/disputes/{DISPUTE_ID}/draft", data=FORM, headers={"Host": "127.0.0.1:8000"})
    assert page.status_code == 403


@pytest.mark.parametrize("origin", [
    "null",  # what a cross-site page with no-referrer, a sandboxed iframe or a data: URL sends
    "http://evil.example",
    "http://127.0.0.1:8001",  # other port
    "https://127.0.0.1:8000",  # other scheme
    "http://localhost:8000",  # other host than the one the page was served from
    "http://127.0.0.1:8000.evil.example",
    "http://127.0.0.1",
    "",
])
def test_foreign_or_null_origin_is_still_refused(make: Any, origin: str) -> None:
    h = make(reply(GOOD), send_mode="live")
    page = _browser_post(h, origin)
    assert page.status_code == 403 and "Cross-origin request refused" in page.text
    _assert_nothing_called(h)


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil.example", "0.0.0.0", "192.168.1.10"])
def test_untrusted_host_header_is_400(make: Any, host: str) -> None:
    h = make()
    page = h.client.get("/", headers={"Host": host})
    assert page.status_code == 400
    _assert_nothing_called(h)


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:8000"])
def test_loopback_host_headers_are_allowed(make: Any, host: str) -> None:
    h = make()
    h.mocked.get(LIST_URL, json=fixture("dispute_list_empty.json"))
    assert h.client.get("/", headers={"Host": host}).status_code == 200


def test_security_headers(make: Any) -> None:
    h = make()
    h.mocked.get(LIST_URL, json=fixture("dispute_list_empty.json"))
    headers = h.client.get("/").headers
    assert "default-src 'none'" in headers["content-security-policy"]
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["cache-control"] == "no-store"


def test_no_api_docs_routes(make: Any) -> None:
    h = make()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert h.client.get(path).status_code == 404


# --- Form input ----------------------------------------------------------------


@pytest.mark.parametrize("form", [
    {"tracking": ""}, {"tracking": "12 34"}, {"tracking": "<b>"}, {"tracking": "1" * 65},
    {"carrier": "UPS"}, {"carrier": "fedex"}, {"carrier": ""},
])
def test_invalid_form_input_is_422_with_no_paypal_or_model_call(make: Any, form: dict[str, str]) -> None:
    h = make(reply(GOOD))
    token = h.csrf.issue(DISPUTE_ID, "draft")
    page = h.client.post(f"/disputes/{DISPUTE_ID}/draft", data={**FORM, **form, "csrf": token})
    assert page.status_code == 422 and "Nothing was sent" in page.text
    _assert_nothing_called(h)


@pytest.mark.parametrize("bad_id", ["bad%20id", "PP_R_1", "%3Cscript%3E", "A" * 65])
def test_invalid_dispute_id_is_400(make: Any, bad_id: str) -> None:
    h = make()
    page = h.client.get(f"/disputes/{bad_id}")
    assert page.status_code == 400 and "Invalid dispute ID" in page.text
    _assert_nothing_called(h)


# --- Row: safe errors ----------------------------------------------------------


def _secret_free(text: str) -> None:
    for secret in (FAKE_TOKEN, FAKE_SECRET, FAKE_CLIENT_ID, *FAKE_BUYER_VALUES):
        assert secret not in text


def test_paypal_error_page_shows_status_issue_and_debug_id_only(make: Any) -> None:
    h = make()
    h.dispute(fixture("error_action_not_allowed.json"), status=400)
    page = h.client.get(f"/disputes/{DISPUTE_ID}")
    assert page.status_code == 502
    for text in ("HTTP 400", "ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE", "f41195223259c"):
        assert text in page.text
    assert "not well-formed" not in page.text  # PayPal's free text is left out
    _secret_free(page.text)


def test_failed_evidence_post_shows_a_safe_error(make: Any) -> None:
    h = make(reply(GOOD), reply(GOOD), send_mode="live")
    h.dispute()
    h.dispute()
    h.ack(status=400, body=fixture("error_action_not_allowed.json"))
    page = h.approve(h.draft())
    assert page.status_code == 502
    assert "HTTP 400" in page.text and "provide-evidence" in page.text
    _secret_free(page.text)


# --- Send outcome: clear rejection (4xx) vs unknown (timeout, dropped connection, 5xx) ---


def _approve_live_with_post(make: Any, **post: Any) -> tuple[Harness, dict[str, str], Any]:
    h = make(reply(GOOD), reply(GOOD), reply(GOOD), send_mode="live")
    h.dispute()
    h.dispute()
    h.dispute(read_back())
    h.mocked.post(EVIDENCE_URL, **post)
    form = approve_form(h.draft().text)
    page = h.client.post(f"/disputes/{DISPUTE_ID}/approve", data=form)
    return h, form, page


def _no_automatic_retry(h: Harness, form: dict[str, str], page: Any) -> None:
    assert f'action="/disputes/{DISPUTE_ID}/approve"' not in page.text  # no retry form offered
    again = h.client.post(f"/disputes/{DISPUTE_ID}/approve", data=form)  # resubmit / refresh
    assert again.status_code == 403  # the approve token was single use
    assert len(h.evidence_posts()) == 1
    assert len(h.model.requests) == 2


@pytest.mark.parametrize("post", [
    {"body": requests.exceptions.ReadTimeout()},
    {"body": requests.exceptions.ConnectTimeout()},
    {"body": requests.exceptions.ConnectionError()},
    {"body": RuntimeError(f"boom {FAKE_TOKEN}")},
    {"json": {"name": "INTERNAL_SERVICE_ERROR", "debug_id": "abc123"}, "status": 500},
    {"json": {"name": "SERVICE_UNAVAILABLE"}, "status": 503},
    {"body": "not json", "status": 200},
], ids=["read-timeout", "connect-timeout", "connection-dropped", "unexpected-error", "http-500", "http-503",
        "unreadable-2xx"])
def test_unknown_send_outcome_says_unknown_and_never_nothing_was_sent(make: Any, post: dict[str, Any]) -> None:
    h, form, page = _approve_live_with_post(make, **post)
    assert page.status_code == 502
    text = page.text
    assert "outcome of the send is unknown" in text
    assert "PayPal may have received the evidence" in text
    assert "Do not retry blindly: open the dispute page and check its state first" in text
    assert f'href="/disputes/{DISPUTE_ID}"' in text
    assert "nothing was sent" not in text.lower() and "nothing more was done" not in text.lower()
    assert "boom" not in text
    _secret_free(text)
    assert len(h.calls("GET", DISPUTE_URL)) == 2  # draft and approve reads; no read-back shown as a result
    _no_automatic_retry(h, form, page)


@pytest.mark.parametrize("status", [400, 403, 404, 422])
def test_clear_rejection_keeps_the_rejected_wording(make: Any, status: int) -> None:
    h, form, page = _approve_live_with_post(make, json=fixture("error_action_not_allowed.json"), status=status)
    assert page.status_code == 502
    assert "Nothing more was done" in page.text and f"HTTP {status}" in page.text
    assert "unknown" not in page.text.lower()
    _secret_free(page.text)
    _no_automatic_retry(h, form, page)


def test_rejected_draft_shows_its_safe_message(make: Any) -> None:
    text_only = ModelResponse(stop_reason="end_turn", text_blocks=1)
    h = make(text_only)
    h.dispute()
    page = h.draft()
    assert page.status_code == 502
    assert "DraftRejected" in page.text and "did not call submit_claims" in page.text
    assert f'action="/disputes/{DISPUTE_ID}/approve"' not in page.text


def test_unexpected_error_is_a_generic_500_and_logs_the_class_name_only(
    make: Any, caplog: pytest.LogCaptureFixture
) -> None:
    h = make(RuntimeError(f"boom {FAKE_TOKEN} FAKE-BUYER-MESSAGE"))
    h.dispute()
    client = TestClient(h.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
    token = h.csrf.issue(DISPUTE_ID, "draft")
    with caplog.at_level(logging.DEBUG):
        page = client.post(f"/disputes/{DISPUTE_ID}/draft", data={**FORM, "csrf": token})
    assert page.status_code == 500 and "Internal error" in page.text
    assert "boom" not in page.text
    _secret_free(page.text)
    assert "internal error: RuntimeError" in caplog.text
    assert "boom" not in caplog.text


def test_no_secret_or_buyer_text_in_pages_or_logs_over_a_full_live_flow(
    make: Any, caplog: pytest.LogCaptureFixture
) -> None:
    h = make(reply(GOOD), reply(GOOD), send_mode="live")
    h.mocked.get(LIST_URL, json=fixture("dispute_list_one.json"))
    h.dispute()
    h.dispute()
    h.dispute()
    h.dispute(read_back())
    h.dispute(read_back())
    h.ack()
    with caplog.at_level(logging.DEBUG):
        pages = [h.client.get("/")]
        draft_page = h.draft()
        pages += [draft_page, h.approve(draft_page), h.client.get(f"/disputes/{DISPUTE_ID}/state")]
    assert all(p.status_code == 200 for p in pages)
    for p in pages:
        _secret_free(p.text)
    _secret_free(caplog.text)


# --- __main__: local bind, dry by default ---------------------------------------


@pytest.fixture
def main_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYPAL_CLIENT_ID", FAKE_CLIENT_ID)
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", FAKE_SECRET)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", MODEL)
    monkeypatch.delenv("DISPUTE_DEFENDER_SEND_MODE", raising=False)


def _run_main(tmp_path: Path, argv: list[str]) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake_run(app: Any, **kwargs: Any) -> None:
        seen["app"] = app
        seen.update(kwargs)

    seen["code"] = web_main.main(argv, env_file=tmp_path / "no.env", run=fake_run)
    return seen


def test_main_binds_loopback_only_and_is_dry_by_default(
    main_env: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = _run_main(tmp_path, [])
    assert seen["code"] == 0
    assert seen["host"] == "127.0.0.1" and seen["port"] == 8000
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "http://127.0.0.1:8000" in out
    _secret_free(out)
    client = TestClient(seen["app"], base_url="http://127.0.0.1")
    assert DRY_BANNER in client.post(f"/disputes/{DISPUTE_ID}/draft", data={}).text


def test_main_live_only_when_set(main_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                 capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("DISPUTE_DEFENDER_SEND_MODE", "live")
    seen = _run_main(tmp_path, ["--port", "8123"])
    assert seen["port"] == 8123 and seen["host"] == "127.0.0.1"
    assert "LIVE SANDBOX SEND" in capsys.readouterr().out


def test_main_has_no_host_option(main_env: None, tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _run_main(tmp_path, ["--host", "0.0.0.0"])


def test_main_reports_missing_config_safely(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("PAYPAL_CLIENT_ID", FAKE_CLIENT_ID)
    seen = _run_main(tmp_path, [])
    assert seen["code"] == 1 and "app" not in seen
    err = capsys.readouterr().err
    assert "PAYPAL_CLIENT_SECRET" in err
    _secret_free(err)
