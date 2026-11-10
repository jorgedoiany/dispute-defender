#!/usr/bin/env python3
"""Live smoke check of dispute_defender.paypal against the PayPal sandbox (T-003).

One step per run. Loads `.env` into the environment, then uses PayPalClient.from_env(),
which refuses any host other than api-m.sandbox.paypal.com. Prints one line per call;
credentials, tokens, raw bodies and buyer details are never printed. `show` also prints
the top-level key NAMES of the dispute JSON (no values) so T-004 can see the real shape;
with --nested-keys it also prints the key NAMES one level down in disputed_transactions[0],
evidences[0], messages[0] and offer.

Steps:
  token
  list
  show              --dispute-id ID [--nested-keys]
  provide-evidence  --dispute-id ID   (placeholder tracking, as in T-002)
  send-message      --dispute-id ID
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dispute_defender.paypal import (  # noqa: E402
    Dispute,
    Evidence,
    PayPalClient,
    PayPalError,
    TrackingInfo,
    check_dispute_id,
)

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
SCOPE_PREFIX = "https://uri.paypal.com/services/disputes/"
MESSAGE = "Sandbox test message from the Dispute Defender T-003 smoke check. No real order exists."
# Placeholder values from PayPal's documented sample; not a real shipment.
EVIDENCE = Evidence(
    tracking_info=[TrackingInfo(carrier_name="FEDEX", tracking_number="122533485")],
    notes="Sandbox test evidence with placeholder tracking; not a real shipment.",
)
# Fields whose key names `show --nested-keys` prints (first element for lists). Names only (T-004).
NESTED_FIELDS = ("disputed_transactions", "evidences", "messages", "offer")


def summary(dispute: Dispute) -> str:
    return (
        f"id={dispute.dispute_id} status={dispute.status} stage={dispute.stage} "
        f"reason={dispute.reason} amount={dispute.amount.value} {dispute.amount.currency_code} "
        f"links={','.join(dispute.link_names()) or 'none'}"
    )


def show(client: PayPalClient, label: str, dispute_id: str) -> Dispute:
    dispute = client.get_dispute(dispute_id)
    print(f"[{label}] OK | {summary(dispute)}")
    return dispute


def step_token(client: PayPalClient, _args: argparse.Namespace) -> None:
    token = client.get_token()
    flags = " ".join(
        f"{name}={'yes' if SCOPE_PREFIX + name in token.scopes else 'NO'}"
        for name in ("read-seller", "update-seller")
    )
    print(f"[token] OK | token obtained; expires_in={token.expires_in}; disputes {flags}")


def step_list(client: PayPalClient, _args: argparse.Namespace) -> None:
    items = client.list_disputes()
    shown = "; ".join(f"{i.dispute_id}/{i.status}/{i.stage}/{i.reason}" for i in items[:5])
    print(f"[list] OK | {len(items)} dispute(s) {shown}")


def nested_key_names(raw: dict, field: str) -> str:
    """Key names (never values) of raw[field], or of its first element if it is a list."""
    if field not in raw:
        return "absent"
    node = raw[field]
    if isinstance(node, list):
        if not node:
            return "empty list"
        node = node[0]
    if not isinstance(node, dict):
        return "not an object"
    return ", ".join(sorted(node)) or "no keys"


def step_show(client: PayPalClient, args: argparse.Namespace) -> None:
    show(client, "show", args.dispute_id)
    raw = client.get_dispute_raw(args.dispute_id)
    print(f"[show] top-level keys (names only): {', '.join(sorted(raw))}")
    if args.nested_keys:
        for field in NESTED_FIELDS:
            where = field if field == "offer" else f"{field}[0]"
            print(f"[show] {where} keys (names only): {nested_key_names(raw, field)}")


def step_action(client: PayPalClient, args: argparse.Namespace) -> None:
    before = show(client, f"{args.step}:before", args.dispute_id)
    if not before.has_link(args.step):
        print(f"  warning: PayPal did not offer the {args.step} link; calling anyway")
    if args.step == "provide-evidence":
        client.provide_evidence(args.dispute_id, [EVIDENCE])
    else:
        client.send_message(args.dispute_id, MESSAGE)
    print(f"[{args.step}] OK | accepted by PayPal")
    show(client, f"{args.step}:after", args.dispute_id)


def dispute_id_arg(value: str) -> str:
    try:
        return check_dispute_id(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="T-003 smoke check of the PayPal client. Sandbox only.")
    steps = parser.add_subparsers(dest="step", required=True)
    steps.add_parser("token").set_defaults(run=step_token)
    steps.add_parser("list").set_defaults(run=step_list)
    dispute = argparse.ArgumentParser(add_help=False)
    dispute.add_argument("--dispute-id", required=True, type=dispute_id_arg)
    show_parser = steps.add_parser("show", parents=[dispute])
    show_parser.add_argument(
        "--nested-keys",
        action="store_true",
        help="also print key names (no values) under " + ", ".join(NESTED_FIELDS),
    )
    show_parser.set_defaults(run=step_show)
    for name in ("provide-evidence", "send-message"):
        steps.add_parser(name, parents=[dispute]).set_defaults(run=step_action)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    load_dotenv(ENV_PATH, override=True)
    try:
        args.run(PayPalClient.from_env(), args)
    except PayPalError as exc:
        print(f"[{args.step}] FAILED | {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
