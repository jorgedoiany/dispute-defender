#!/usr/bin/env python3
"""PayPal sandbox spike for T-002. Sandbox only; each step is its own subcommand.

Run `python scripts/spike_sandbox.py --help` for the steps. Each HTTP call prints
one line. Credentials, tokens, headers, raw bodies and buyer details are never
printed. Steps that need a person in the browser print MANUAL ACTION and exit.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
SANDBOX_HOST = "api-m.sandbox.paypal.com"
SANDBOX_WEB = "https://www.sandbox.paypal.com"
TIMEOUT_SECONDS = 30
DISPUTES = "/v1/customer/disputes"
ORDERS = "/v2/checkout/orders"
SCOPE_PREFIX = "https://uri.paypal.com/services/disputes/"
STATUS = "status"
STAGE = "dispute_life_cycle_stage"

MESSAGE = "Sandbox test message from the Dispute Defender spike. No real order exists."
ESCALATE_NOTE = "Sandbox test escalation from the Dispute Defender spike."
# Placeholder values taken from PayPal's documented sample; not a real shipment.
EVIDENCE = {
    "evidences": [
        {
            "evidence_type": "PROOF_OF_FULFILLMENT",
            "evidence_info": {
                "tracking_info": [{"carrier_name": "FEDEX", "tracking_number": "122533485"}]
            },
            "notes": "Sandbox test evidence with placeholder tracking; not a real shipment.",
        }
    ]
}

_SECRETS: list[str] = []


class SpikeError(Exception):
    """A failure that ends the step; its message is safe to print."""


class Action(NamedTuple):
    field: str
    expected: str
    link: str
    next_hint: str


ACTIONS = {
    "send-message": Action(STAGE, "INQUIRY", "send-message", "Next: escalate."),
    "escalate": Action(
        STAGE, "INQUIRY", "escalate", "Next: run show until status is UNDER_REVIEW, then require-evidence."
    ),
    "require-evidence": Action(STATUS, "UNDER_REVIEW", "require-evidence", "Next: provide-evidence."),
    "provide-evidence": Action(
        STATUS, "WAITING_FOR_SELLER_RESPONSE", "provide-evidence",
        "Next: run show until status is UNDER_REVIEW, then adjudicate.",
    ),
    "adjudicate": Action(STATUS, "UNDER_REVIEW", "adjudicate", "Dispute settled. The spike is complete."),
}


def clean(value: Any, limit: int = 240) -> str:
    """Return a one-line, length-limited string with known secrets removed."""
    text = " ".join(str(value).split())
    for secret in _SECRETS:
        text = text.replace(secret, "***")
    return text[:limit]


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def error_text(body: dict[str, Any]) -> str:
    """Summarize a PayPal error using selected fields only."""
    keys = ("name", "message", "error", "error_description", "debug_id")
    parts = [f"{key}={clean(body[key])}" for key in keys if body.get(key)]
    issues = [clean(as_dict(item).get("issue")) for item in as_list(body.get("details"))]
    if any(issue != "None" for issue in issues):
        parts.append("issues=" + ",".join(issues))
    return " ".join(parts) or "no error details returned"


def report(step: str, status: int, success_text: str, body: dict[str, Any]) -> bool:
    ok = 200 <= status < 300
    print(f"[{step}] HTTP {status} | " + (clean(success_text) if ok else f"FAILED {error_text(body)}"))
    return ok


def manual(*lines: str) -> None:
    print("MANUAL ACTION REQUIRED (browser). The script stops here.")
    for line in lines:
        print(f"  - {line}")


def load_config() -> tuple[str, str, str]:
    load_dotenv(ENV_PATH, override=True)
    client_id = os.getenv("PAYPAL_CLIENT_ID", "").strip()
    secret = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
    missing = [
        name
        for name, value in (("PAYPAL_CLIENT_ID", client_id), ("PAYPAL_CLIENT_SECRET", secret))
        if not value
    ]
    if missing:
        raise SpikeError(f"missing in .env: {', '.join(missing)}")
    base = os.getenv("PAYPAL_BASE_URL", f"https://{SANDBOX_HOST}").strip().rstrip("/")
    parts = urlsplit(base)
    if parts.scheme != "https" or parts.hostname != SANDBOX_HOST or parts.path:
        raise SpikeError(f"refusing to run: PAYPAL_BASE_URL must be https://{SANDBOX_HOST}")
    return client_id, secret, base


class Client:
    """Minimal REST client that authenticates when created."""

    def __init__(self) -> None:
        client_id, secret, self.base = load_config()
        _SECRETS.extend([client_id, secret])
        self.token_status, body = self._send(
            "POST",
            "/v1/oauth2/token",
            auth=(client_id, secret),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
        )
        token = body.get("access_token")
        if self.token_status != 200 or not isinstance(token, str) or not token:
            raise SpikeError(f"[token] HTTP {self.token_status} | FAILED {error_text(body)}")
        self.token = token
        _SECRETS.append(token)
        self.scopes = str(body.get("scope", "")).split()
        self.expires_in = body.get("expires_in")

    def _send(self, method: str, path: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        try:
            response = requests.request(
                method, self.base + path, timeout=TIMEOUT_SECONDS, allow_redirects=False, **kwargs
            )
        except requests.RequestException as exc:
            raise SpikeError(f"network error on {method} {path}: {type(exc).__name__}") from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        return response.status_code, as_dict(body)

    def call(self, method: str, path: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            **kwargs.pop("headers", {}),
        }
        return self._send(method, path, headers=headers, **kwargs)


def link_names(body: dict[str, Any]) -> list[str]:
    rels = (as_dict(link).get("rel") for link in as_list(body.get("links")))
    return sorted({str(rel).replace("_", "-") for rel in rels if rel})


def money(value: Any) -> str:
    amount = as_dict(value)
    return f"{amount.get('value')} {amount.get('currency_code')}"


def dispute_summary(body: dict[str, Any]) -> str:
    outcome = as_dict(body.get("dispute_outcome")).get("outcome_code")
    return (
        f"id={body.get('dispute_id')} status={body.get(STATUS)} stage={body.get(STAGE)} "
        f"reason={body.get('reason')} amount={money(body.get('dispute_amount'))} "
        f"outcome={outcome} links={','.join(link_names(body)) or 'none'}"
    )


def show_dispute(client: Client, step: str, dispute_id: str) -> tuple[bool, dict[str, Any]]:
    status, body = client.call("GET", f"{DISPUTES}/{dispute_id}")
    return report(step, status, dispute_summary(body), body), body


def cmd_token(client: Client, _args: argparse.Namespace) -> bool:
    granted = {name: SCOPE_PREFIX + name in client.scopes for name in ("read-seller", "update-seller")}
    flags = " ".join(f"{name}={'yes' if value else 'NO'}" for name, value in granted.items())
    report("token", client.token_status, f"token obtained; expires_in={client.expires_in}; disputes {flags}", {})
    if not all(granted.values()):
        manual("Enable the disputes feature on this sandbox app in the PayPal Developer Dashboard.", "Run token again.")
    return True


def cmd_create_order(client: Client, _args: argparse.Namespace) -> bool:
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "description": "Dispute Defender sandbox spike",
                "amount": {"currency_code": "USD", "value": "10.00"},
            }
        ],
        "payment_source": {
            "paypal": {
                "experience_context": {
                    "user_action": "PAY_NOW",
                    "return_url": "https://example.com/return",
                    "cancel_url": "https://example.com/cancel",
                }
            }
        },
    }
    status, body = client.call("POST", ORDERS, json=payload)
    if not report("create-order", status, f"order_id={body.get('id')} status={body.get(STATUS)}", body):
        return False
    href = next(
        (
            str(as_dict(link).get("href"))
            for link in as_list(body.get("links"))
            if as_dict(link).get("rel") in ("payer-action", "approve")
        ),
        "",
    )
    host = urlsplit(href).hostname or ""
    if host != "sandbox.paypal.com" and not host.endswith(".sandbox.paypal.com"):
        raise SpikeError("order created, but PayPal returned no sandbox approval link")
    manual(
        f"Open this link and log in as the sandbox buyer: {href}",
        "Approve the payment. Landing on example.com afterwards is expected.",
        f"Then run: capture --order-id {clean(body.get('id'))}",
    )
    return True


def cmd_capture(client: Client, args: argparse.Namespace) -> bool:
    status, body = client.call(
        "POST",
        f"{ORDERS}/{args.order_id}/capture",
        json={},
        headers={"Prefer": "return=representation"},
    )
    unit = as_dict(next(iter(as_list(body.get("purchase_units"))), {}))
    capture = as_dict(next(iter(as_list(as_dict(unit.get("payments")).get("captures"))), {}))
    result = (
        f"order_status={body.get(STATUS)} capture_id={capture.get('id')} "
        f"capture_status={capture.get(STATUS)} amount={money(capture.get('amount'))}"
    )
    if not report("capture", status, result, body):
        return False
    manual(
        f"Log in at {SANDBOX_WEB} as the sandbox buyer and open the Resolution Center.",
        'Report a problem with this payment and choose "item not received".',
        "Then run list until the dispute appears, and use its ID for the next steps.",
    )
    return True


def cmd_list(client: Client, _args: argparse.Namespace) -> bool:
    status, body = client.call("GET", DISPUTES, params={"page_size": 20})
    items = [as_dict(item) for item in as_list(body.get("items"))]
    shown = "; ".join(
        f"{item.get('dispute_id')}/{item.get(STATUS)}/{item.get(STAGE)}/{item.get('reason')}" for item in items[:5]
    )
    ok = report("list", status, f"{len(items)} dispute(s) {shown}", body)
    if ok and not items:
        print("  No disputes yet. A new sandbox case can take time to appear; run list again later.")
    return ok


def cmd_show(client: Client, args: argparse.Namespace) -> bool:
    return show_dispute(client, "show", args.dispute_id)[0]


def multipart(payload: dict[str, Any]) -> dict[str, Any]:
    return {"files": {"input": (None, json.dumps(payload), "application/json")}}


def action_request(args: argparse.Namespace) -> dict[str, Any]:
    if args.step == "send-message":
        payload = {"message": MESSAGE}
        return {"json": payload} if args.format == "json" else multipart(payload)
    if args.step == "escalate":
        return {"json": {"note": ESCALATE_NOTE}}
    if args.step == "require-evidence":
        return {"json": {"action": "SELLER_EVIDENCE"}}
    if args.step == "provide-evidence":
        return multipart(EVIDENCE)
    return {"json": {"adjudication_outcome": args.outcome}}


def cmd_action(client: Client, args: argparse.Namespace) -> bool:
    action = ACTIONS[args.step]
    found, before = show_dispute(client, f"{args.step}:before", args.dispute_id)
    if not found:
        return False
    if before.get(action.field) != action.expected:
        print(f"  warning: expected {action.field}={action.expected}, got {clean(before.get(action.field))}; calling anyway")
    if action.link not in link_names(before):
        print(f"  warning: PayPal did not offer the {action.link} link; calling anyway")
    status, body = client.call("POST", f"{DISPUTES}/{args.dispute_id}/{args.step}", **action_request(args))
    ok = report(args.step, status, "accepted by PayPal", body)
    show_dispute(client, f"{args.step}:after", args.dispute_id)
    if ok:
        print(f"  {action.next_hint}")
    return ok


def resource_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", value):
        raise argparse.ArgumentTypeError("must contain only letters, digits and hyphens")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PayPal sandbox spike (T-002). Sandbox only.")
    steps = parser.add_subparsers(dest="step", required=True)
    steps.add_parser("token", help="get an OAuth token and report disputes scopes").set_defaults(run=cmd_token)
    steps.add_parser("create-order", help="create an order for the buyer to approve").set_defaults(run=cmd_create_order)
    capture = steps.add_parser("capture", help="capture an approved order")
    capture.add_argument("--order-id", required=True, type=resource_id)
    capture.set_defaults(run=cmd_capture)
    steps.add_parser("list", help="list disputes").set_defaults(run=cmd_list)

    dispute = argparse.ArgumentParser(add_help=False)
    dispute.add_argument("--dispute-id", required=True, type=resource_id)
    steps.add_parser("show", parents=[dispute], help="show one dispute").set_defaults(run=cmd_show)
    for name in ACTIONS:
        action = steps.add_parser(name, parents=[dispute], help=f"call {name} on a dispute")
        action.set_defaults(run=cmd_action)
        if name == "send-message":
            action.add_argument("--format", choices=("json", "multipart"), default="json")
        if name == "adjudicate":
            action.add_argument("--outcome", required=True, choices=("SELLER_FAVOR", "BUYER_FAVOR"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return 0 if args.run(Client(), args) else 1
    except SpikeError as exc:
        print(f"ERROR: {clean(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
