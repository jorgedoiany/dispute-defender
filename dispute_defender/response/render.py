"""Render the response text from VERIFIED claims only (T-006, ADR-009, ADR-010).

A pure function: no model, network or clock. The model never writes text for PayPal
or the buyer; this template does, from claim values the verifier marked VERIFIED.
FLAGGED and BLOCKED claims are ignored.

One sentence per VERIFIED claim, in this fixed order, joined with a single space:
  transaction_id     The disputed payment is PayPal transaction {id}.
  amount             The transaction amount was {value} {currency}.
  transaction_date   The transaction was made on {date} (UTC).
  seller_protection  PayPal lists this transaction as eligible for Seller Protection.
                     (only if the VERIFIED value is true)
  tracking_number    According to our records, the order was shipped with {carrier},
  + carrier          tracking number {tracking}. (only if both are VERIFIED)

Returns None (nothing to send) when no claim is VERIFIED, when two VERIFIED claims
share a type, or when no sentence results. Values are written as the claim holds
them; only the carrier is trimmed, because the verifier compares it trimmed. A
VERIFIED value of an unexpected shape also gives None, so rendering fails closed.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from dispute_defender.claims import ClaimResult, Verdict


class _Unrenderable(Exception):
    pass


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _Unrenderable
    return value


def _sentences(values: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if "transaction_id" in values:
        out.append(f"The disputed payment is PayPal transaction {_text(values['transaction_id'])}.")
    if "amount" in values:
        amount = values["amount"]
        if not isinstance(amount, dict):
            raise _Unrenderable
        out.append(
            f"The transaction amount was {_text(amount.get('value'))} {_text(amount.get('currency_code'))}."
        )
    if "transaction_date" in values:
        out.append(f"The transaction was made on {_text(values['transaction_date'])} (UTC).")
    if "seller_protection" in values:
        protected = values["seller_protection"]
        if type(protected) is not bool:
            raise _Unrenderable
        if protected:
            out.append("PayPal lists this transaction as eligible for Seller Protection.")
    if "tracking_number" in values and "carrier" in values:
        carrier = _text(values["carrier"]).strip()
        tracking = _text(values["tracking_number"])
        out.append(
            f"According to our records, the order was shipped with {carrier}, tracking number {tracking}."
        )
    return out


def render_notes(results: Sequence[ClaimResult]) -> str | None:
    values: dict[str, Any] = {}
    for result in results:
        if result.verdict is not Verdict.VERIFIED:
            continue
        if result.claim.type in values:
            return None  # two VERIFIED claims of one type: refuse rather than pick one
        values[result.claim.type] = result.claim.value
    if not values:
        return None
    try:
        sentences = _sentences(values)
    except _Unrenderable:
        return None
    return " ".join(sentences) or None
