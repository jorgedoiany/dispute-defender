"""Offline tests for the VERIFIED-only response renderer (T-006, ADR-010)."""
from __future__ import annotations

from typing import Any

import pytest

from dispute_defender.claims import Claim, ClaimResult, MerchantOrderRecord, Verdict, verify_claims
from dispute_defender.paypal import Dispute
from dispute_defender.response import render_notes

from .conftest import fixture

TXN_ID = "54X87564PT289050U"  # seller_transaction_id in dispute_inquiry_waiting.json
RECORD = MerchantOrderRecord(transaction_id=TXN_ID, tracking_number="122533485", carrier="FEDEX")

S_TXN = f"The disputed payment is PayPal transaction {TXN_ID}."
S_AMOUNT = "The transaction amount was 10.00 USD."
S_DATE = "The transaction was made on 2026-11-09 (UTC)."
S_PROTECTION = "PayPal lists this transaction as eligible for Seller Protection."
S_SHIPPED = "According to our records, the order was shipped with FEDEX, tracking number 122533485."

GOOD = {
    "transaction_id": ("paypal", TXN_ID),
    "amount": ("paypal", {"value": "10.00", "currency_code": "USD"}),
    "transaction_date": ("paypal", "2026-11-09"),
    "seller_protection": ("paypal", True),
    "tracking_number": ("merchant_record", "122533485"),
    "carrier": ("merchant_record", "FEDEX"),
}


def claim(type_: str, value: Any = None, source: str | None = None) -> Claim:
    default_source, default_value = GOOD.get(type_, ("paypal", "x"))
    return Claim(type=type_, value=default_value if value is None else value, source=source or default_source)


def verified(*claims: Claim) -> list[ClaimResult]:
    """Run the real verifier on the fixture dispute."""
    return verify_claims(Dispute.model_validate(fixture("dispute_inquiry_waiting.json")), claims, RECORD)


def result(c: Claim, verdict: Verdict = Verdict.VERIFIED) -> ClaimResult:
    """A hand-built result, for shapes the verifier would not produce."""
    return ClaimResult(claim=c, verdict=verdict, checked_against="paypal", reason="test")


def test_all_verified_renders_every_sentence_in_fixed_order() -> None:
    results = verified(*(claim(t) for t in GOOD))
    assert all(r.verdict is Verdict.VERIFIED for r in results)
    assert render_notes(results) == " ".join([S_TXN, S_AMOUNT, S_DATE, S_PROTECTION, S_SHIPPED])


def test_output_does_not_depend_on_claim_order() -> None:
    forward = verified(*(claim(t) for t in GOOD))
    assert render_notes(list(reversed(forward))) == render_notes(forward)


@pytest.mark.parametrize(
    ("types", "expected"),
    [
        (["transaction_id"], S_TXN),
        (["amount"], S_AMOUNT),
        (["transaction_date"], S_DATE),
        (["seller_protection"], S_PROTECTION),
        (["tracking_number", "carrier"], S_SHIPPED),
        (["amount", "transaction_id"], f"{S_TXN} {S_AMOUNT}"),
        (["carrier", "transaction_date", "tracking_number"], f"{S_DATE} {S_SHIPPED}"),
    ],
)
def test_subsets_render_exact_text(types: list[str], expected: str) -> None:
    assert render_notes(verified(*(claim(t) for t in types))) == expected


def test_no_claims_gives_none() -> None:
    assert render_notes([]) is None


def test_blocked_and_flagged_claims_are_never_rendered() -> None:
    results = verified(
        claim("amount", {"value": "12.00", "currency_code": "USD"}),  # BLOCKED: wrong amount
        claim("transaction_date", "2026-11-10"),  # BLOCKED: wrong date
        claim("tracking_number", "000"),  # BLOCKED: not the record's tracking
        claim("carrier", "FEDEX"),
        claim("refund_issued", True),  # FLAGGED: unsupported type
        claim("transaction_id", TXN_ID, source="merchant_record"),  # FLAGGED: wrong source
    )
    verdicts = [r.verdict for r in results]
    assert verdicts.count(Verdict.BLOCKED) == 3 and verdicts.count(Verdict.FLAGGED) == 2
    notes = render_notes(results)
    # Only the carrier is VERIFIED, and it alone renders nothing.
    assert notes is None


def test_blocked_values_do_not_leak_next_to_verified_ones() -> None:
    results = verified(
        claim("transaction_id"),
        claim("amount", {"value": "12.00", "currency_code": "USD"}),
        claim("tracking_number", "000"),
        claim("carrier"),
    )
    notes = render_notes(results)
    assert notes == S_TXN
    assert "12.00" not in notes and "000" not in notes and "FEDEX" not in notes


def test_only_flagged_or_blocked_gives_none() -> None:
    results = [result(claim("amount"), Verdict.BLOCKED), result(claim("transaction_id"), Verdict.FLAGGED)]
    assert render_notes(results) is None


def test_seller_protection_false_renders_no_sentence() -> None:
    d = fixture("dispute_inquiry_waiting.json")
    d["disputed_transactions"][0]["seller_protection_eligible"] = False
    results = verify_claims(Dispute.model_validate(d), [claim("seller_protection", False)], RECORD)
    assert results[0].verdict is Verdict.VERIFIED
    assert render_notes(results) is None
    assert render_notes(results + verified(claim("transaction_id"))) == S_TXN


@pytest.mark.parametrize("missing", ["tracking_number", "carrier"])
def test_shipping_sentence_needs_both_tracking_and_carrier(missing: str) -> None:
    other = "carrier" if missing == "tracking_number" else "tracking_number"
    assert render_notes(verified(claim("transaction_id"), claim(other))) == S_TXN


def test_duplicate_verified_type_gives_none() -> None:
    results = verified(claim("transaction_id"), claim("amount"), claim("amount"))
    assert all(r.verdict is Verdict.VERIFIED for r in results)
    assert render_notes(results) is None


def test_duplicate_type_with_one_blocked_is_not_a_duplicate() -> None:
    results = verified(claim("amount"), claim("amount", {"value": "12.00", "currency_code": "USD"}))
    assert render_notes(results) == S_AMOUNT


@pytest.mark.parametrize("written", [" fedex ", "FedEx", "FEDEX"])
def test_carrier_is_written_as_its_canonical_value(written: str) -> None:
    results = verified(claim("tracking_number"), claim("carrier", written))
    assert results[1].verdict is Verdict.VERIFIED
    assert render_notes(results) == S_SHIPPED


def test_carrier_outside_the_list_gives_no_shipping_sentence() -> None:
    record = MerchantOrderRecord(transaction_id=TXN_ID, tracking_number="122533485", carrier="UPS")
    d = Dispute.model_validate(fixture("dispute_inquiry_waiting.json"))
    results = verify_claims(d, [claim("transaction_id"), claim("tracking_number"), claim("carrier", "UPS")], record)
    assert all(r.verdict is Verdict.VERIFIED for r in results)
    notes = render_notes(results)
    assert notes == S_TXN
    assert "UPS" not in notes


def test_amount_value_is_written_as_claimed() -> None:
    results = verified(claim("amount", {"value": "10.0", "currency_code": "USD"}))
    assert results[0].verdict is Verdict.VERIFIED
    assert render_notes(results) == "The transaction amount was 10.0 USD."


@pytest.mark.parametrize(
    "bad",
    [
        claim("amount", "10.00 USD"),
        claim("amount", {"value": 10, "currency_code": "USD"}),
        claim("transaction_id", 123),
        claim("transaction_date", ""),
        claim("seller_protection", "true"),
    ],
)
def test_unexpected_shape_in_a_verified_result_fails_closed(bad: Claim) -> None:
    assert render_notes([result(claim("transaction_id")), result(bad)]) is None


def test_unknown_type_marked_verified_is_ignored() -> None:
    results = [result(claim("transaction_id")), result(Claim(type="free_text", value="<b>hi</b>", source="paypal"))]
    assert render_notes(results) == S_TXN
