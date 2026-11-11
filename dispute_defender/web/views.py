"""Plain display values for the templates (T-006).

Templates autoescape; these helpers also remove control, bidi and zero-width characters
and cut long values, so a hostile value cannot reorder or flood the page. Buyer message
text is never passed to a template: only the number of messages is.
"""
from __future__ import annotations

import json
from datetime import timezone
from typing import Any

from dispute_defender.claims import ClaimResult
from dispute_defender.drafter.prompt import _UNSAFE_CHARS  # same character set as the prompt cleaner
from dispute_defender.paypal import Dispute

MAX_SHOWN_CHARS = 200
CUT = " [cut]"


def shown(value: Any, limit: int | None = MAX_SHOWN_CHARS) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            text = type(value).__name__
    text = _UNSAFE_CHARS.sub("", text)
    if limit is not None and len(text) > limit:
        text = text[:limit] + CUT
    return text


def dispute_view(dispute: Dispute) -> dict[str, Any]:
    view: dict[str, Any] = {
        "dispute_id": shown(dispute.dispute_id),
        "status": shown(dispute.status),
        "stage": shown(dispute.stage),
        "reason": shown(dispute.reason),
        "amount": shown(f"{dispute.amount.value} {dispute.amount.currency_code}"),
        "links": [shown(name) for name in dispute.link_names()],
        "response_options": [shown(name) for name in dispute.response_option_names],
        "message_count": len(dispute.messages),
        "transaction_count": len(dispute.transactions),
        "transaction": None,
    }
    if len(dispute.transactions) == 1:
        txn = dispute.transactions[0]
        view["transaction"] = {
            "id": shown(txn.seller_transaction_id),
            "date_utc": shown(txn.create_time.astimezone(timezone.utc).date().isoformat() if txn.create_time else None),
            "amount": shown(f"{txn.gross_amount.value} {txn.gross_amount.currency_code}" if txn.gross_amount else None),
            "seller_protection_eligible": shown(txn.seller_protection_eligible),
        }
    return view


def claim_views(results: list[ClaimResult]) -> list[dict[str, str]]:
    return [
        {
            "type": shown(r.claim.type, 60),
            "source": shown(r.claim.source, 60),
            "value": shown(r.claim.value),
            "verdict": r.verdict.value,
            "reason": shown(r.reason, 300),
        }
        for r in results
    ]
