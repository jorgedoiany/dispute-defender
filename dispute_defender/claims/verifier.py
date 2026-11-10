"""Deterministic claim verifier (T-004, ADR-008).

No model calls, no network, no clock. Each claim is checked in this order:
  1. unknown claim type                      -> FLAGGED
  2. missing source, or wrong source for type -> FLAGGED
  3. invalid value                           -> BLOCKED
  4. no data to check against                -> FLAGGED
  5. compare: match -> VERIFIED, mismatch    -> BLOCKED

PayPal-backed types read the single entry of `Dispute.transactions`; zero or several
entries give FLAGGED so a claim is never checked against the wrong transaction.

Rules:
  transaction_id     exact, case-sensitive match with seller_transaction_id
  amount             {"value": "10.00", "currency_code": "USD"}; Decimal equality of the
                     value ("10.0" == "10.00") and exact currency match with gross_amount
  transaction_date   "YYYY-MM-DD" compared with the UTC calendar date of create_time.
                     A merchant's local date can differ near midnight and is then BLOCKED.
  seller_protection  JSON true/false, exact match with seller_protection_eligible
  tracking_number    exact match with the merchant record
  carrier            match with the merchant record, trimmed and case-insensitive

Merchant-record results say "verified against merchant record", never that PayPal verified them.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timezone
from decimal import Decimal
from typing import Any, NoReturn

from dispute_defender.paypal.models import Dispute, DisputedTransaction

from .models import (
    SOURCE_MERCHANT_RECORD,
    SOURCE_PAYPAL,
    Claim,
    ClaimResult,
    MerchantOrderRecord,
    Verdict,
)

_AMOUNT_RE = re.compile(r"^[0-9]+(\.[0-9]+)?$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

_PAYPAL_OK = "verified against PayPal transaction data"
_PAYPAL_BAD = "contradicts PayPal transaction data"
_RECORD_OK = "verified against merchant record"
_RECORD_BAD = "contradicts merchant record"


class _Stop(Exception):
    def __init__(self, verdict: Verdict, reason: str) -> None:
        super().__init__(reason)
        self.verdict = verdict
        self.reason = reason


def _flag(reason: str) -> NoReturn:
    raise _Stop(Verdict.FLAGGED, reason)


def _block(reason: str) -> NoReturn:
    raise _Stop(Verdict.BLOCKED, reason)


def _invalid(reason: str) -> NoReturn:
    _block(f"invalid value: {reason}")


@dataclass(frozen=True)
class _Context:
    dispute: Dispute
    record: MerchantOrderRecord | None


@dataclass(frozen=True)
class _Rule:
    source: str
    parse: Callable[[Any], Any]  # returns the parsed value or calls _invalid
    check: Callable[[Any, _Context], str]  # returns the VERIFIED reason or calls _flag/_block


# Value parsers (step 3)


def _parse_text(value: Any) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        _invalid("expected a non-empty string without surrounding whitespace")
    return value


def _parse_carrier(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid("expected a non-empty string")
    return value.strip()


def _parse_amount(value: Any) -> tuple[Decimal, str]:
    if not isinstance(value, dict) or set(value) != {"value", "currency_code"}:
        _invalid('expected {"value": "<decimal string>", "currency_code": "<ISO code>"}')
    raw, currency = value["value"], value["currency_code"]
    if not isinstance(raw, str) or not _AMOUNT_RE.fullmatch(raw):
        _invalid("amount value must be a decimal string such as \"10.00\"")
    amount = Decimal(raw)
    if amount <= 0:
        _invalid("amount value must be greater than zero")
    if not isinstance(currency, str) or not _CURRENCY_RE.fullmatch(currency):
        _invalid("currency_code must be three upper-case letters")
    return amount, currency


def _parse_date(value: Any) -> date:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        _invalid("expected a date as YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        _invalid("not a real calendar date")


def _parse_bool(value: Any) -> bool:
    if type(value) is not bool:
        _invalid("expected true or false")
    return value


# Data access (step 4)


def _transaction(dispute: Dispute) -> DisputedTransaction:
    count = len(dispute.transactions)
    if count != 1:
        _flag(f"PayPal data has {count} disputed transactions; expected exactly one")
    return dispute.transactions[0]


def _record_field(ctx: _Context, field: str) -> str:
    record = ctx.record
    if record is None:
        _flag("no merchant record provided")
    if record.transaction_id is not None:
        txns = ctx.dispute.transactions
        dispute_txn = txns[0].seller_transaction_id if len(txns) == 1 else None
        if dispute_txn is None:
            _flag("cannot confirm the merchant record is for this dispute's transaction")
        if record.transaction_id != dispute_txn:
            _flag(
                f"merchant record is for a different transaction "
                f"({record.transaction_id}, dispute transaction {dispute_txn})"
            )
    found = getattr(record, field)
    if found is None:
        _flag(f"merchant record has no {field}")
    return found


# Comparisons (step 5)


def _check_transaction_id(claimed: str, ctx: _Context) -> str:
    actual = _transaction(ctx.dispute).seller_transaction_id
    if actual is None:
        _flag("PayPal transaction data has no seller_transaction_id")
    if claimed != actual:
        _block(f"{_PAYPAL_BAD}: claimed transaction ID {claimed}, PayPal shows {actual}")
    return f"{_PAYPAL_OK}: transaction ID matches"


def _check_amount(claimed: tuple[Decimal, str], ctx: _Context) -> str:
    actual = _transaction(ctx.dispute).gross_amount
    if actual is None:
        _flag("PayPal transaction data has no gross_amount")
    value, currency = claimed
    diffs = []
    if value != actual.value:
        diffs.append(f"value {value} vs {actual.value}")
    if currency != actual.currency_code:
        diffs.append(f"currency {currency} vs {actual.currency_code}")
    if diffs:
        _block(f"{_PAYPAL_BAD}: claimed vs PayPal gross amount: {'; '.join(diffs)}")
    return f"{_PAYPAL_OK}: amount {actual.value} {actual.currency_code} matches"


def _check_date(claimed: date, ctx: _Context) -> str:
    created = _transaction(ctx.dispute).create_time
    if created is None:
        _flag("PayPal transaction data has no create_time")
    actual = created.astimezone(timezone.utc).date()
    if claimed != actual:
        _block(f"{_PAYPAL_BAD}: claimed date {claimed}, PayPal shows {actual} (UTC)")
    return f"{_PAYPAL_OK}: transaction date {actual} (UTC) matches"


def _check_protection(claimed: bool, ctx: _Context) -> str:
    actual = _transaction(ctx.dispute).seller_protection_eligible
    if actual is None:
        _flag("PayPal transaction data has no seller_protection_eligible")
    if claimed != actual:
        _block(f"{_PAYPAL_BAD}: claimed seller protection eligible={claimed}, PayPal shows {actual}")
    return f"{_PAYPAL_OK}: seller protection eligibility matches"


def _check_tracking(claimed: str, ctx: _Context) -> str:
    actual = _record_field(ctx, "tracking_number")
    if claimed != actual:
        _block(f"{_RECORD_BAD}: claimed tracking number {claimed}, record shows {actual}")
    return f"{_RECORD_OK}: tracking number matches"


def _check_carrier(claimed: str, ctx: _Context) -> str:
    actual = _record_field(ctx, "carrier")
    if claimed.casefold() != actual.strip().casefold():
        _block(f"{_RECORD_BAD}: claimed carrier {claimed}, record shows {actual}")
    return f"{_RECORD_OK}: carrier matches"


RULES: dict[str, _Rule] = {
    "transaction_id": _Rule(SOURCE_PAYPAL, _parse_text, _check_transaction_id),
    "amount": _Rule(SOURCE_PAYPAL, _parse_amount, _check_amount),
    "transaction_date": _Rule(SOURCE_PAYPAL, _parse_date, _check_date),
    "seller_protection": _Rule(SOURCE_PAYPAL, _parse_bool, _check_protection),
    "tracking_number": _Rule(SOURCE_MERCHANT_RECORD, _parse_text, _check_tracking),
    "carrier": _Rule(SOURCE_MERCHANT_RECORD, _parse_carrier, _check_carrier),
}
SUPPORTED_CLAIM_TYPES = frozenset(RULES)


def verify_claim(
    dispute: Dispute, claim: Claim, merchant_record: MerchantOrderRecord | None = None
) -> ClaimResult:
    rule = RULES.get(claim.type)
    if rule is None:
        return ClaimResult(
            claim=claim, verdict=Verdict.FLAGGED, checked_against=None,
            reason=f"unsupported claim type {claim.type!r}",
        )
    if claim.source != rule.source:
        reason = (
            f"no source given; claim type {claim.type!r} is checked against {rule.source}"
            if not claim.source
            else f"claim type {claim.type!r} is checked against {rule.source}, not {claim.source!r}"
        )
        return ClaimResult(claim=claim, verdict=Verdict.FLAGGED, checked_against=None, reason=reason)
    try:
        parsed = rule.parse(claim.value)
        reason = rule.check(parsed, _Context(dispute, merchant_record))
    except _Stop as stop:
        return ClaimResult(claim=claim, verdict=stop.verdict, checked_against=rule.source, reason=stop.reason)
    return ClaimResult(claim=claim, verdict=Verdict.VERIFIED, checked_against=rule.source, reason=reason)


def verify_claims(
    dispute: Dispute, claims: Iterable[Claim], merchant_record: MerchantOrderRecord | None = None
) -> list[ClaimResult]:
    """Verify each claim independently; results keep the order of `claims`."""
    return [verify_claim(dispute, claim, merchant_record) for claim in claims]
