"""Offline tests for the deterministic claim verifier (T-004)."""
from __future__ import annotations

from typing import Any

import pytest

from dispute_defender.claims import (
    SUPPORTED_CLAIM_TYPES,
    Claim,
    ClaimResult,
    MerchantOrderRecord,
    Verdict,
    verify_claim,
    verify_claims,
)
from dispute_defender.paypal import Dispute

from .conftest import fixture

TXN_ID = "54X87564PT289050U"  # seller_transaction_id in dispute_inquiry_waiting.json
RECORD = MerchantOrderRecord(transaction_id=TXN_ID, tracking_number="122533485", carrier="FEDEX")

MATCHING = {
    "transaction_id": ("paypal", TXN_ID),
    "amount": ("paypal", {"value": "10.00", "currency_code": "USD"}),
    "transaction_date": ("paypal", "2026-11-09"),
    "seller_protection": ("paypal", True),
    "tracking_number": ("merchant_record", "122533485"),
    "carrier": ("merchant_record", "FEDEX"),
}


def dispute(**txn_changes: Any) -> Dispute:
    body = fixture("dispute_inquiry_waiting.json")
    txn = body["disputed_transactions"][0]
    for key, value in txn_changes.items():
        if value is None:
            txn.pop(key, None)
        else:
            txn[key] = value
    return Dispute.model_validate(body)


def check(type_: str, value: Any, source: str | None = None, *, d: Dispute | None = None,
          record: MerchantOrderRecord | None = RECORD) -> ClaimResult:
    if source is None and type_ in MATCHING:
        source = MATCHING[type_][0]
    return verify_claim(d or dispute(), Claim(type=type_, value=value, source=source), record)


# Matching claims


def test_every_supported_type_has_a_matching_case() -> None:
    assert set(MATCHING) == SUPPORTED_CLAIM_TYPES


@pytest.mark.parametrize("type_", sorted(MATCHING))
def test_matching_claim_is_verified(type_: str) -> None:
    source, value = MATCHING[type_]
    result = check(type_, value, source)
    assert result.verdict is Verdict.VERIFIED, result.reason
    assert result.checked_against == source


def test_amount_compares_decimal_value() -> None:
    assert check("amount", {"value": "10.0", "currency_code": "USD"}).verdict is Verdict.VERIFIED


def test_paypal_reason_names_paypal_data() -> None:
    assert check("amount", MATCHING["amount"][1]).reason.startswith("verified against PayPal transaction data")


# Mismatches against PayPal data


def test_amount_value_mismatch_is_blocked() -> None:
    result = check("amount", {"value": "12.00", "currency_code": "USD"})
    assert result.verdict is Verdict.BLOCKED
    assert "value 12.00 vs 10.00" in result.reason and "currency" not in result.reason


def test_currency_mismatch_is_blocked() -> None:
    result = check("amount", {"value": "10.00", "currency_code": "EUR"})
    assert result.verdict is Verdict.BLOCKED
    assert "currency EUR vs USD" in result.reason and "value" not in result.reason.split(":", 2)[-1]


def test_amount_and_currency_mismatch_names_both() -> None:
    result = check("amount", {"value": "9.99", "currency_code": "EUR"})
    assert result.verdict is Verdict.BLOCKED
    assert "value 9.99 vs 10.00" in result.reason and "currency EUR vs USD" in result.reason


def test_wrong_date_is_blocked() -> None:
    result = check("transaction_date", "2026-11-08")
    assert result.verdict is Verdict.BLOCKED
    assert "2026-11-09 (UTC)" in result.reason


def test_date_uses_utc_calendar_day() -> None:
    late_local = dispute(create_time="2026-11-09T23:30:00-05:00")  # 2026-11-10 04:30 UTC
    assert check("transaction_date", "2026-11-10", d=late_local).verdict is Verdict.VERIFIED
    assert check("transaction_date", "2026-11-09", d=late_local).verdict is Verdict.BLOCKED


def test_wrong_transaction_id_is_blocked() -> None:
    result = check("transaction_id", "54X87564PT289050X")
    assert result.verdict is Verdict.BLOCKED


def test_transaction_id_is_case_sensitive() -> None:
    assert check("transaction_id", TXN_ID.lower()).verdict is Verdict.BLOCKED


def test_seller_protection_mismatch_is_blocked() -> None:
    assert check("seller_protection", False).verdict is Verdict.BLOCKED


# Missing data, unknown type, source problems


@pytest.mark.parametrize(
    ("type_", "missing"),
    [
        ("transaction_id", "seller_transaction_id"),
        ("amount", "gross_amount"),
        ("transaction_date", "create_time"),
        ("seller_protection", "seller_protection_eligible"),
    ],
)
def test_missing_paypal_data_is_flagged(type_: str, missing: str) -> None:
    result = check(type_, MATCHING[type_][1], d=dispute(**{missing: None}))
    assert result.verdict is Verdict.FLAGGED
    assert missing in result.reason


@pytest.mark.parametrize("count", [0, 2])
def test_not_exactly_one_transaction_is_flagged(count: int) -> None:
    body = fixture("dispute_inquiry_waiting.json")
    body["disputed_transactions"] = body["disputed_transactions"] * count
    result = check("amount", MATCHING["amount"][1], d=Dispute.model_validate(body))
    assert result.verdict is Verdict.FLAGGED
    assert f"{count} disputed transactions" in result.reason


def test_fixtures_without_transaction_fields_flag_paypal_claims() -> None:
    d = Dispute.model_validate(fixture("dispute_chargeback.json"))
    assert check("amount", MATCHING["amount"][1], d=d).verdict is Verdict.FLAGGED


def test_unknown_claim_type_is_flagged() -> None:
    result = check("delivery_signature", "J. Doe", "paypal")
    assert result.verdict is Verdict.FLAGGED
    assert result.checked_against is None
    assert "unsupported claim type" in result.reason


@pytest.mark.parametrize("source", [None, ""])
def test_missing_source_is_flagged(source: str | None) -> None:
    result = verify_claim(dispute(), Claim(type="amount", value=MATCHING["amount"][1], source=source))
    assert result.verdict is Verdict.FLAGGED
    assert "no source" in result.reason


@pytest.mark.parametrize(
    ("type_", "source"),
    [("amount", "merchant_record"), ("tracking_number", "paypal"), ("carrier", "shipping_label")],
)
def test_wrong_source_for_type_is_flagged(type_: str, source: str) -> None:
    result = check(type_, MATCHING[type_][1], source)
    assert result.verdict is Verdict.FLAGGED
    assert result.checked_against is None


# Invalid values


@pytest.mark.parametrize(
    ("type_", "value"),
    [
        ("amount", {"value": "ten", "currency_code": "USD"}),
        ("amount", {"value": 10.0, "currency_code": "USD"}),
        ("amount", {"value": "-1.00", "currency_code": "USD"}),
        ("amount", {"value": "0.00", "currency_code": "USD"}),
        ("amount", {"value": "NaN", "currency_code": "USD"}),
        ("amount", {"value": "10.00", "currency_code": "usd"}),
        ("amount", {"value": "10.00"}),
        ("amount", "10.00 USD"),
        ("transaction_date", "11/09/2026"),
        ("transaction_date", "2026-02-30"),
        ("transaction_date", "20261109"),
        ("seller_protection", "true"),
        ("seller_protection", 1),
        ("transaction_id", ""),
        ("transaction_id", " 54X87564PT289050U"),
        ("transaction_id", 123),
        ("tracking_number", None),
        ("carrier", "   "),
    ],
)
def test_invalid_value_is_blocked(type_: str, value: Any) -> None:
    result = check(type_, value)
    assert result.verdict is Verdict.BLOCKED
    assert result.reason.startswith("invalid value:")


def test_invalid_value_is_blocked_even_without_data() -> None:
    result = check("amount", {"value": "ten", "currency_code": "USD"}, d=dispute(gross_amount=None))
    assert result.verdict is Verdict.BLOCKED


# Merchant-record claims


@pytest.mark.parametrize("type_", ["tracking_number", "carrier"])
def test_merchant_claim_without_record_is_flagged(type_: str) -> None:
    result = check(type_, MATCHING[type_][1], record=None)
    assert result.verdict is Verdict.FLAGGED
    assert result.reason == "no merchant record provided"


def test_merchant_record_reason_wording() -> None:
    result = check("tracking_number", "122533485")
    assert result.reason == "verified against merchant record: tracking number matches"


def test_tracking_number_mismatch_is_blocked() -> None:
    assert check("tracking_number", "122533486").verdict is Verdict.BLOCKED


def test_tracking_number_is_exact() -> None:
    record = MerchantOrderRecord(tracking_number="1Z999AA10123456784")
    assert check("tracking_number", "1z999aa10123456784", record=record).verdict is Verdict.BLOCKED


@pytest.mark.parametrize("claimed", ["fedex", " FedEx ", "FEDEX"])
def test_carrier_is_trimmed_and_case_insensitive(claimed: str) -> None:
    assert check("carrier", claimed).verdict is Verdict.VERIFIED


def test_carrier_mismatch_is_blocked() -> None:
    assert check("carrier", "UPS").verdict is Verdict.BLOCKED


def test_record_without_the_field_is_flagged() -> None:
    result = check("carrier", "FEDEX", record=MerchantOrderRecord(tracking_number="122533485"))
    assert result.verdict is Verdict.FLAGGED
    assert "no carrier" in result.reason


@pytest.mark.parametrize(
    ("record_txn", "verdict"),
    [(TXN_ID, Verdict.VERIFIED), (None, Verdict.VERIFIED), ("OTHER-TXN-0000", Verdict.FLAGGED)],
    ids=["match", "absent", "mismatch"],
)
@pytest.mark.parametrize("type_", ["tracking_number", "carrier"])
def test_record_transaction_id(type_: str, record_txn: str | None, verdict: Verdict) -> None:
    record = MerchantOrderRecord(transaction_id=record_txn, tracking_number="122533485", carrier="FEDEX")
    result = check(type_, MATCHING[type_][1], record=record)
    assert result.verdict is verdict
    if verdict is Verdict.FLAGGED:
        assert "merchant record is for a different transaction" in result.reason


def test_record_mismatch_is_flagged_even_if_claim_contradicts_record() -> None:
    record = MerchantOrderRecord(transaction_id="OTHER-TXN-0000", tracking_number="999")
    assert check("tracking_number", "122533485", record=record).verdict is Verdict.FLAGGED


def test_record_transaction_id_unconfirmable_is_flagged() -> None:
    result = check("carrier", "FEDEX", d=dispute(seller_transaction_id=None))
    assert result.verdict is Verdict.FLAGGED
    assert "cannot confirm" in result.reason


def test_merchant_record_results_never_mention_paypal() -> None:
    other = MerchantOrderRecord(transaction_id="OTHER-TXN-0000", tracking_number="1", carrier="UPS")
    results = [
        check(type_, value, record=record)
        for type_ in ("tracking_number", "carrier")
        for value in (MATCHING[type_][1], "mismatch", "")
        for record in (RECORD, other, None, MerchantOrderRecord())
    ]
    assert {r.verdict for r in results} == set(Verdict)
    for result in results:
        assert result.checked_against == "merchant_record"
        assert "paypal" not in result.reason.lower()


# Batch


def test_verify_claims_keeps_order_and_is_independent() -> None:
    claims = [
        Claim(type="carrier", value="UPS", source="merchant_record"),
        Claim(type="amount", value={"value": "10.00", "currency_code": "USD"}, source="paypal"),
        Claim(type="mystery", value=1, source="paypal"),
    ]
    results = verify_claims(dispute(), claims, RECORD)
    assert [r.claim for r in results] == claims
    assert [r.verdict for r in results] == [Verdict.BLOCKED, Verdict.VERIFIED, Verdict.FLAGGED]


def test_claim_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        Claim.model_validate({"type": "amount", "value": "1", "source": "paypal", "verified": True})
