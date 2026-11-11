"""Offline UI preview of the approval pages (T-012). No PayPal, no Bedrock, no network.

Renders every page through the real app (`create_app`, its Jinja environment with
autoescape on, its routes and view helpers) and writes static HTML files:
  - PayPal answers come from a stub HTTP session that returns the hand-written test
    fixtures in tests/fixtures/paypal/ (plus a few labelled fake variants);
  - the model is a fake client with fixed claims;
  - CSRF uses a fixed fake token ("FAKE-CSRF-TOKEN-preview-only").
No `.env` or environment variable is read. Needs requirements-dev.txt (FastAPI's
TestClient uses httpx).

Usage: .venv/bin/python scripts/preview_ui.py [--out DIR]   (default: ui-preview/, gitignored)
Then open ui-preview/index.html in a browser. Links between pages point at app routes
and do not work in the static files.
"""
from __future__ import annotations

import argparse
import copy
import html
import json
import re
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from dispute_defender.drafter import TOOL_NAME, ModelRequest, ModelResponse, ToolUse  # noqa: E402
from dispute_defender.paypal import PayPalClient, PayPalConfig  # noqa: E402
from dispute_defender.web import CsrfTokens, create_app  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "paypal"
DEFAULT_OUT = ROOT / "ui-preview"
FAKE_CSRF = "FAKE-CSRF-TOKEN-preview-only"
DISPUTE_ID = "PP-R-HBV-10197617"  # the id in the hand-written fixtures
DISPUTES = "/v1/customer/disputes"
DISPUTE = f"{DISPUTES}/{DISPUTE_ID}"
EVIDENCE = f"{DISPUTE}/provide-evidence"
FIXED_NOW = datetime(2026, 11, 10, 18, 30, 5, tzinfo=timezone.utc)
FORM = {"tracking": "122533485", "carrier": "FEDEX"}
TXN_ID = "54X87564PT289050U"

# Claims the fake model returns: VERIFIED, BLOCKED and (with the dispute below) FLAGGED.
CLAIMS = [
    {"type": "transaction_id", "source": "paypal", "value": TXN_ID},
    {"type": "amount", "source": "paypal", "value": {"value": "10.00", "currency_code": "USD"}},
    {"type": "amount", "source": "paypal", "value": {"value": "12.00", "currency_code": "USD"}},  # BLOCKED
    {"type": "transaction_date", "source": "paypal", "value": "2026-11-09"},
    {"type": "seller_protection", "source": "paypal", "value": True},  # FLAGGED: field removed below
    {"type": "tracking_number", "source": "merchant_record", "value": "122533485"},
    {"type": "carrier", "source": "merchant_record", "value": "FedEx"},
]

Reply = tuple[int, Any]  # (HTTP status, JSON body) or (0, exception to raise)


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def sendable() -> dict[str, Any]:
    body = fixture("dispute_inquiry_waiting.json")
    body["allowed_response_options"] = {"accept_claim": {}}
    return body


def for_draft() -> dict[str, Any]:
    body = sendable()
    del body["disputed_transactions"][0]["seller_protection_eligible"]  # gives one FLAGGED claim
    return body


def with_state(status: str, rels: tuple[str, ...]) -> dict[str, Any]:
    body = fixture("dispute_inquiry_waiting.json")
    body["status"] = status
    body["links"] = [link for link in body["links"] if link["rel"] in rels]
    return body


def dispute_list() -> dict[str, Any]:
    body = fixture("dispute_list_one.json")
    fake = copy.deepcopy(body["items"][0])
    fake.update(dispute_id="PP-R-FAKE-00000001", status="UNDER_REVIEW", dispute_life_cycle_stage="CHARGEBACK",
                dispute_amount={"currency_code": "USD", "value": "25.50"})  # fake row, for the preview only
    body["items"].append(fake)
    return body


class _Response:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code = status
        self._body = body
        self.content = json.dumps(body).encode()

    def json(self) -> Any:
        return self._body


class StubSession:
    """Answers PayPalClient's requests from fixed replies; anything else is an error. No network."""

    def __init__(self, routes: dict[tuple[str, str], list[Reply]]) -> None:
        self.routes = {key: list(replies) for key, replies in routes.items()}

    def request(self, method: str, url: str, **_kwargs: Any) -> _Response:
        path = urlsplit(url).path
        if path == "/v1/oauth2/token":
            return _Response(200, fixture("token.json"))
        replies = self.routes.get((method, path))
        if not replies:
            raise RuntimeError(f"preview stub has no reply for {method} {path}")
        status, body = replies.pop(0) if len(replies) > 1 else replies[0]
        if isinstance(body, Exception):
            raise body
        return _Response(status, body)


class FakeModel:
    def converse(self, _request: ModelRequest) -> ModelResponse:
        return ModelResponse(stop_reason="tool_use",
                             tool_uses=(ToolUse(name=TOOL_NAME, input={"claims": copy.deepcopy(CLAIMS)}),))


class FakeCsrf(CsrfTokens):
    """Fixed fake token, accepted everywhere. For the offline preview only."""

    def __init__(self) -> None:
        super().__init__(b"preview-only-not-a-real-key-0000")

    def issue(self, dispute_id: str, purpose: str) -> str:
        return FAKE_CSRF

    def consume(self, token: object, dispute_id: str, purpose: str) -> bool:
        return True


def client_for(routes: dict[tuple[str, str], list[Reply]], *, live: bool = False) -> TestClient:
    paypal = PayPalClient(PayPalConfig(client_id="FAKE-PREVIEW-ID", client_secret="FAKE-PREVIEW-SECRET"),
                          session=StubSession(routes))  # type: ignore[arg-type]
    app = create_app(paypal=paypal, model_client=FakeModel(), model_id="fake-model-for-preview",
                     send_mode="live" if live else "dry", csrf=FakeCsrf(), now=lambda: FIXED_NOW)
    return TestClient(app, base_url="http://127.0.0.1")


def approve_data(draft_page: str) -> dict[str, str]:
    form = draft_page[draft_page.index(f'action="/disputes/{DISPUTE_ID}/approve"'):]
    form = form[:form.index("</form>")]
    return {m.group(1): html.unescape(m.group(2)) for m in re.finditer(r'name="([a-z_]+)" value="([^"]*)"', form)}


def _list() -> list[tuple[str, str]]:
    page = client_for({("GET", DISPUTES): [(200, dispute_list())]}).get("/")
    return [("01-list.html", page.text)]


def _dispute() -> list[tuple[str, str]]:
    page = client_for({("GET", DISPUTE): [(200, sendable())]}).get(f"/disputes/{DISPUTE_ID}")
    return [("02-dispute.html", page.text)]


def _dispute_refused() -> list[tuple[str, str]]:
    page = client_for({("GET", DISPUTE): [(200, fixture("dispute_under_review.json"))]}).get(f"/disputes/{DISPUTE_ID}")
    return [("03-dispute-refused.html", page.text)]


def _flow(live: bool) -> list[tuple[str, str]]:
    suffix = "live" if live else "dry"
    after = with_state("UNDER_REVIEW", ("self",)) if live else for_draft()
    client = client_for({
        ("GET", DISPUTE): [(200, for_draft()), (200, for_draft()), (200, after)],
        ("POST", EVIDENCE): [(200, fixture("action_ack.json"))],
    }, live=live)
    draft = client.post(f"/disputes/{DISPUTE_ID}/draft", data={**FORM, "csrf": FAKE_CSRF})
    result = client.post(f"/disputes/{DISPUTE_ID}/approve", data=approve_data(draft.text))
    return [(f"04-draft-{suffix}.html", draft.text), (f"05-result-{suffix}.html", result.text)]


def _state() -> list[tuple[str, str]]:
    body = with_state("WAITING_FOR_BUYER_RESPONSE", ("accept_claim", "escalate", "self", "send_message"))
    page = client_for({("GET", DISPUTE): [(200, body)]}).get(f"/disputes/{DISPUTE_ID}/state")
    return [("06-state.html", page.text)]


def _messages() -> list[tuple[str, str]]:
    refused = client_for({("GET", DISPUTE): [(200, fixture("dispute_under_review.json"))]}).post(
        f"/disputes/{DISPUTE_ID}/approve", data={**FORM, "csrf": FAKE_CSRF, "shown_hash": "0" * 64})
    paypal_error = client_for({("GET", DISPUTE): [(400, fixture("error_action_not_allowed.json"))]}).get(
        f"/disputes/{DISPUTE_ID}")
    timeout = client_for({
        ("GET", DISPUTE): [(200, for_draft())],
        ("POST", EVIDENCE): [(0, requests.exceptions.ReadTimeout())],
    }, live=True)
    draft = timeout.post(f"/disputes/{DISPUTE_ID}/draft", data={**FORM, "csrf": FAKE_CSRF})
    unknown = timeout.post(f"/disputes/{DISPUTE_ID}/approve", data=approve_data(draft.text))
    bad_input = client_for({}).post(f"/disputes/{DISPUTE_ID}/draft",
                                    data={"tracking": "not valid!", "carrier": "FEDEX", "csrf": FAKE_CSRF})
    return [("07-message-refused.html", refused.text), ("08-error-paypal.html", paypal_error.text),
            ("09-error-send-outcome-unknown.html", unknown.text), ("10-error-invalid-input.html", bad_input.text)]


PAGES: list[Callable[[], list[tuple[str, str]]]] = [
    _list, _dispute, _dispute_refused, lambda: _flow(False), lambda: _flow(True), _state, _messages,
]


def render_all(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for render in PAGES:
        for name, text in render():
            path = out_dir / name
            path.write_text(text, encoding="utf-8")
            written.append(path)
    items = "\n".join(f'<li><a href="{p.name}">{p.name}</a></li>' for p in written)
    index = out_dir / "index.html"
    index.write_text(
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><title>UI preview</title></head>\n"
        "<body><h1>Dispute Defender UI preview (offline, fake data)</h1>\n"
        "<p>Rendered by scripts/preview_ui.py from test fixtures and fake values. Links inside the pages "
        "point at app routes and do not work here.</p>\n"
        f"<ul>\n{items}\n</ul></body></html>\n",
        encoding="utf-8",
    )
    return [index, *written]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the approval pages offline to static HTML (T-012).")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder (default: ui-preview/)")
    args = parser.parse_args(argv)
    paths = render_all(args.out)
    print(f"[preview] wrote {len(paths)} files to {args.out}")
    print(f"[preview] open {paths[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
