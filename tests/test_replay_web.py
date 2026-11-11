"""Replay mode in the web app (T-010, ADR-012). Offline.

The app is the real create_app() with the two replay clients. Network is blocked on top
of conftest's guards (requests via `responses`, botocore's send): any socket connect fails.
"""
from __future__ import annotations

import html
import importlib.util
import json
import re
import socket
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dispute_defender.claims import MerchantOrderRecord, Verdict, verify_claims
from dispute_defender.drafter import draft_claims
from dispute_defender.paypal import PayPalClient, PayPalConfig
from dispute_defender.replay import ReplayModelClient, ReplayPayPalClient, load_replay, replay_model_label
from dispute_defender.response import SendPlan, notes_hash, prepare_send, render_notes
from dispute_defender.web import CsrfTokens, create_app

from .conftest import FAKE_CLIENT_ID, FAKE_SECRET

REPLAY_BANNER = "REPLAY: recorded and simulated data, not real PayPal data. Nothing leaves this machine."
DRY_BANNER = "DRY RUN: nothing will be sent"
LIVE_BANNER = "LIVE SANDBOX SEND"
PAYPAL_READ_WORDING = ("Read from PayPal", "read from PayPal at", "Read back from PayPal", "PayPal sandbox only",
                       "Sent to the PayPal sandbox", "Actions PayPal offers")
D1, D2, D3 = "PP-R-SIM-N1", "PP-R-SIM-REPLAY2", "PP-R-SIM-REPLAY3"
FORM1 = {"tracking": "SIM100000001", "carrier": "FEDEX"}
FORM3 = {"tracking": "SIM100000002", "carrier": "FEDEX"}
INJECTED_LABEL = "SIMULATED model error injected to demonstrate the verifier"


@pytest.fixture(autouse=True)
def _no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("replay mode tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


class Replay:
    def __init__(self) -> None:
        data = load_replay()
        self.paypal = ReplayPayPalClient(data)
        self.model = ReplayModelClient(data)
        self.tokens = CsrfTokens()
        self.app = create_app(paypal=self.paypal, model_client=self.model, model_id=replay_model_label(data),
                              send_mode="replay", csrf=self.tokens)
        self.client = TestClient(self.app, base_url="http://127.0.0.1")

    def token(self, page: str, name: str = "csrf") -> str:
        match = re.search(rf'name="{name}" value="([^"]*)"', page)
        assert match, f"no {name} on the page"
        return html.unescape(match.group(1))

    def dispute(self, did: str) -> str:
        page = self.client.get(f"/disputes/{did}")
        assert page.status_code == 200
        return page.text

    def draft(self, did: str, form: dict[str, str]) -> Any:
        token = self.token(self.dispute(did))
        return self.client.post(f"/disputes/{did}/draft", data={**form, "csrf": token})

    def approve(self, did: str, form: dict[str, str], *, shown_hash: str | None = None) -> Any:
        draft = self.draft(did, form)
        assert draft.status_code == 200, draft.text
        data = {name: self.token(draft.text, name) for name in ("csrf", "tracking", "carrier", "shown_hash")}
        if shown_hash is not None:
            data["shown_hash"] = shown_hash
        return self.client.post(f"/disputes/{did}/approve", data=data)


@pytest.fixture
def replay() -> Replay:
    return Replay()


def verdicts(page: str) -> dict[str, str]:
    rows = re.findall(r"<tr><td>([a-z_]+)</td><td>[a-z_]+</td><td>.*?</td><td class=\"(\w+)\">", page)
    return dict(rows)


def assert_replay_page(text: str) -> None:
    assert REPLAY_BANNER in text
    assert DRY_BANNER not in text and LIVE_BANNER not in text
    for wording in PAYPAL_READ_WORDING:
        assert wording not in text, wording


# --- the three disputes -------------------------------------------------------


def test_list_shows_the_three_replay_disputes(replay: Replay) -> None:
    page = replay.client.get("/").text
    assert_replay_page(page)
    for did in (D1, D2, D3):
        assert f'href="/disputes/{did}"' in page
    assert "Replayed from local data" in page and "not read from PayPal" in page


def test_dispute_1_full_flow_records_the_gate_payload(replay: Replay) -> None:
    page = replay.dispute(D1)
    assert_replay_page(page)
    assert "SIMULATED: scenario N1" in page and "RECORDED: claims made by us.anthropic.claude-sonnet-4-6" in page
    assert "SIM100000001" in page  # the tracking hint

    draft = replay.draft(D1, FORM1)
    assert_replay_page(draft.text)
    assert set(verdicts(draft.text).values()) == {"VERIFIED"} and len(verdicts(draft.text)) == 6
    assert "Approve (replay)" in draft.text

    result = replay.approve(D1, FORM1)
    assert result.status_code == 200
    assert_replay_page(result.text)
    assert "Recorded by the local replay client. Nothing was sent to PayPal or anywhere else." in result.text
    assert "Replayed dispute state (hand-written, not read from PayPal)" in result.text
    assert re.search(r">\s*UNDER_REVIEW\s*<", result.text)

    (sent,) = replay.paypal.sent[D1]
    assert sent == [expected_payload(D1, FORM1)]


def expected_payload(did: str, form: dict[str, str]) -> dict[str, object]:
    """What the real pipeline builds for this dispute, computed independently of the app."""
    paypal, model = ReplayPayPalClient(), ReplayModelClient()
    dispute = paypal.get_dispute(did)
    record = MerchantOrderRecord(tracking_number=form["tracking"], carrier=form["carrier"])
    results = verify_claims(dispute, draft_claims(dispute, record, client=model, model_id="x").claims, record)
    notes = render_notes(results)
    assert notes is not None
    plan = prepare_send(dispute, results, notes_hash(notes))
    assert isinstance(plan, SendPlan)
    return plan.evidence.to_payload()


def test_dispute_2_is_refused_before_any_model_call(replay: Replay) -> None:
    page = replay.dispute(D2)
    assert_replay_page(page)
    assert "Cannot respond now" in page and 'name="tracking"' not in page
    assert "SIMULATED: hand-written for T-010" in page
    refused = replay.client.post(f"/disputes/{D2}/draft",
                                 data={**FORM1, "csrf": replay.tokens.issue(D2, "draft")})
    assert refused.status_code == 409
    assert_replay_page(refused.text)
    assert replay.model.requests == [] and replay.paypal.sent == {}


def test_dispute_3_blocked_and_flagged_never_reach_the_payload(replay: Replay) -> None:
    page = replay.dispute(D3)
    assert INJECTED_LABEL in page and "SIM100000002" in page
    draft = replay.draft(D3, FORM3)
    assert_replay_page(draft.text)
    assert INJECTED_LABEL in draft.text
    assert verdicts(draft.text) == {
        "transaction_id": "VERIFIED", "amount": "BLOCKED", "transaction_date": "VERIFIED",
        "seller_protection": "FLAGGED", "tracking_number": "VERIFIED", "carrier": "VERIFIED",
    }
    result = replay.approve(D3, FORM3)
    assert result.status_code == 200
    (sent,) = replay.paypal.sent[D3]
    assert sent == [expected_payload(D3, FORM3)]
    text = json.dumps(sent)
    for value in ("250.00", "250", "25.00", "Seller Protection", "amount was"):
        assert value not in text
    assert "SIMRP3TXN00000001" in text and "SIM100000002" in text


def test_wrong_tracking_is_blocked_and_nothing_recorded(replay: Replay) -> None:
    draft = replay.draft(D1, {"tracking": "WRONG123", "carrier": "FEDEX"})
    assert draft.status_code == 200
    assert verdicts(draft.text)["tracking_number"] == "BLOCKED"
    assert "Cannot send" in draft.text and 'name="shown_hash"' not in draft.text
    assert replay.paypal.sent == {}


def test_hash_mismatch_records_nothing(replay: Replay) -> None:
    page = replay.approve(D1, FORM1, shown_hash="0" * 64)
    assert page.status_code == 409 and "Nothing was sent" in page.text
    assert_replay_page(page.text)
    assert replay.paypal.sent == {}


def test_after_send_state_is_replayed_and_a_second_send_is_refused(replay: Replay) -> None:
    replay.approve(D1, FORM1)
    state = replay.client.get(f"/disputes/{D1}/state").text
    assert_replay_page(state)
    assert "Replayed state at" in state and "not read from PayPal" in state
    assert re.search(r">\s*UNDER_REVIEW\s*<", state)
    assert 'name="tracking"' not in replay.dispute(D1)  # the dispute page no longer offers the form
    again = replay.client.post(f"/disputes/{D1}/draft", data={**FORM1, "csrf": replay.tokens.issue(D1, "draft")})
    assert again.status_code == 409 and "provide-evidence" in again.text
    assert len(replay.paypal.sent[D1]) == 1


# --- banner on every page, including errors ------------------------------------


def test_banner_on_error_pages(replay: Replay) -> None:
    pages = [
        replay.client.get("/disputes/PP-R-SIM-UNKNOWN"),  # PayPal error page (404 from the replay client)
        replay.client.get("/disputes/bad%20id"),  # 400
        replay.client.post(f"/disputes/{D1}/draft", data={**FORM1, "csrf": "forged"}),  # 403
        replay.client.post(f"/disputes/{D1}/draft",
                           data={"tracking": "<x>", "carrier": "FEDEX",
                                 "csrf": replay.token(replay.dispute(D1))}),  # 422
    ]
    assert [p.status_code for p in pages] == [502, 400, 403, 422]
    for page in pages:
        assert_replay_page(page.text)


def test_every_page_escapes_and_has_no_external_resources(replay: Replay) -> None:
    pages = [replay.client.get("/").text, replay.dispute(D1), replay.dispute(D2), replay.dispute(D3),
             replay.draft(D3, FORM3).text, replay.approve(D1, FORM1).text,
             replay.client.get(f"/disputes/{D1}/state").text]
    for page in pages:
        assert_replay_page(page)
        assert "<script" not in page and "FAKE-BUYER" not in page


# --- create_app guards -----------------------------------------------------------


def real_paypal() -> PayPalClient:
    return PayPalClient(PayPalConfig(client_id=FAKE_CLIENT_ID, client_secret=FAKE_SECRET))


class OtherModel:
    def converse(self, _request: Any) -> Any:
        raise AssertionError("not called")


@pytest.mark.parametrize("mode, paypal, model", [
    ("replay", real_paypal, ReplayModelClient),
    ("replay", ReplayPayPalClient, OtherModel),
    ("replay", real_paypal, OtherModel),
    ("dry", ReplayPayPalClient, ReplayModelClient),
    ("live", ReplayPayPalClient, OtherModel),
    ("live", real_paypal, ReplayModelClient),
])
def test_create_app_refuses_mixed_clients(mode: str, paypal: Any, model: Any) -> None:
    with pytest.raises(ValueError, match="replay"):
        create_app(paypal=paypal(), model_client=model(), model_id="m", send_mode=mode)  # type: ignore[arg-type]


# --- dry and live pages carry no replay text --------------------------------------


def test_dry_and_live_pages_have_no_replay_text(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parent.parent / "scripts" / "preview_ui.py"
    spec = importlib.util.spec_from_file_location("preview_ui_replay_check", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--out", str(tmp_path)]) == 0
    for page in tmp_path.glob("*.html"):
        body = re.sub(r"<style>.*?</style>", "", page.read_text(), flags=re.DOTALL)
        assert "REPLAY" not in body and "Replay" not in body and "replay" not in body, page.name
