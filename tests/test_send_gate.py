"""Offline tests for the send gate and evidence payload (T-006, ADR-010)."""
from __future__ import annotations

import json
from typing import Any

import pytest

from dispute_defender.claims import Claim, ClaimResult, MerchantOrderRecord, Verdict, verify_claims
from dispute_defender.paypal import Dispute
from dispute_defender.response import (
    ALLOWED_CARRIERS,
    MAX_NOTES_CHARS,
    Refusal,
    SendPlan,
    check_dispute_sendable,
    notes_hash,
    prepare_send,
    render_notes,
)

from .conftest import fixture

TXN_ID = "54X87564PT289050U"  # seller_transaction_id in dispute_inquiry_waiting.json
RECORD = MerchantOrderRecord(transaction_id=TXN_ID, tracking_number="122533485", carrier="FEDEX")

GOOD = {
    "transaction_id": ("paypal", TXN_ID),
    "amount": ("paypal", {"value": "10.00", "currency_code": "USD"}),
    "transaction_date": ("paypal", "2026-11-09"),
    "seller_protection": ("paypal", True),
    "tracking_number": ("merchant_record", "122533485"),
    "carrier": ("merchant_record", "FEDEX"),
}


def sendable_dispute() -> Dispute:
    """WAITING_FOR_SELLER_RESPONSE / INQUIRY with the provide_evidence link."""
    return Dispute.model_validate(fixture("dispute_inquiry_waiting.json"))


def claim(type_: str, value: Any = None) -> Claim:
    source, default = GOOD[type_]
    return Claim(type=type_, value=default if value is None else value, source=source)


def verified(*claims: Claim, record: MerchantOrderRecord = RECORD) -> list[ClaimResult]:
    return verify_claims(sendable_dispute(), claims, record)


def all_good() -> list[ClaimResult]:
    return verified(*(claim(t) for t in GOOD))


def hash_of(results: list[ClaimResult]) -> str:
    notes = render_notes(results)
    assert notes is not None
    return notes_hash(notes)


def refused(outcome: SendPlan | Refusal, *words: str) -> None:
    assert isinstance(outcome, Refusal), outcome
    for word in words:
        assert word in outcome.reason


# Happy path


def test_all_verified_builds_the_payload_from_verified_values() -> None:
    results = all_good()
    outcome = prepare_send(sendable_dispute(), results, hash_of(results))
    assert isinstance(outcome, SendPlan)
    assert outcome.notes == render_notes(results)
    assert outcome.notes_hash == notes_hash(outcome.notes)
    assert outcome.evidence.to_payload() == {
        "evidence_type": "PROOF_OF_FULFILLMENT",
        "evidence_info": {"tracking_info": [{"carrier_name": "FEDEX", "tracking_number": "122533485"}]},
        "notes": outcome.notes,
    }


def test_minimal_sendable_set_is_tracking_and_carrier() -> None:
    results = verified(claim("tracking_number"), claim("carrier"))
    outcome = prepare_send(sendable_dispute(), results, hash_of(results))
    assert isinstance(outcome, SendPlan)
    assert outcome.notes == "According to our records, the order was shipped with FEDEX, tracking number 122533485."


@pytest.mark.parametrize("written", [" fedex ", "FedEx"])
def test_text_and_payload_use_the_same_canonical_carrier(written: str) -> None:
    results = verified(claim("tracking_number"), claim("carrier", written))
    assert results[1].verdict is Verdict.VERIFIED
    outcome = prepare_send(sendable_dispute(), results, hash_of(results))
    assert isinstance(outcome, SendPlan)
    assert outcome.evidence.tracking_info[0].carrier_name == "FEDEX"
    assert "shipped with FEDEX," in outcome.notes
    assert written.strip() not in outcome.notes.replace("FEDEX", "")


def test_notes_hash_is_sha256_hex() -> None:
    assert notes_hash("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


# Rule 1: the provide_evidence link


def _without_provide_evidence() -> Dispute:
    body = fixture("dispute_inquiry_waiting.json")
    body["status"] = "WAITING_FOR_BUYER_RESPONSE"
    body["links"] = [link for link in body["links"] if link["rel"] != "provide_evidence"]
    return Dispute.model_validate(body)


@pytest.mark.parametrize("make", [
    lambda: Dispute.model_validate(fixture("dispute_under_review.json")),
    _without_provide_evidence,
])
def test_refused_when_link_not_offered(make: Any) -> None:
    d = make()
    assert not d.has_link("provide_evidence")
    refused(check_dispute_sendable(d), "does not offer provide-evidence", d.status, d.stage)
    results = all_good()
    refused(prepare_send(d, results, hash_of(results)), "does not offer provide-evidence")


def test_link_check_passes_on_a_sendable_dispute() -> None:
    assert check_dispute_sendable(sendable_dispute()) is None


def test_allowed_response_options_is_never_a_condition() -> None:
    body = fixture("dispute_inquiry_waiting.json")
    body["allowed_response_options"] = {"accept_claim": {}, "make_offer": {}}
    d = Dispute.model_validate(body)
    assert d.response_option_names == ["accept_claim", "make_offer"]
    results = all_good()
    assert isinstance(prepare_send(d, results, hash_of(results)), SendPlan)

    body = fixture("dispute_under_review.json")
    body["allowed_response_options"] = {"provide_evidence": {}}
    refused(prepare_send(Dispute.model_validate(body), results, hash_of(results)), "does not offer")


# Rules 2 and 3: VERIFIED claims only


def test_refused_when_nothing_is_verified() -> None:
    results = verified(claim("amount", {"value": "12.00", "currency_code": "USD"}), claim("tracking_number", "000"))
    assert {r.verdict for r in results} == {Verdict.BLOCKED}
    assert render_notes(results) is None
    refused(prepare_send(sendable_dispute(), results, "0" * 64), "tracking number and the carrier VERIFIED")


def test_refused_when_render_notes_returns_none_on_duplicate_type() -> None:
    results = all_good() + verified(claim("transaction_id"))
    assert render_notes(results) is None
    refused(prepare_send(sendable_dispute(), results, hash_of(all_good())), "nothing to send")


def test_refused_when_render_notes_returns_none_on_bad_shape() -> None:
    results = verified(claim("tracking_number"), claim("carrier")) + [
        ClaimResult(claim=Claim(type="amount", value="10.00 USD", source="paypal"),
                    verdict=Verdict.VERIFIED, checked_against="paypal", reason="test"),
    ]
    assert render_notes(results) is None
    refused(prepare_send(sendable_dispute(), results, "0" * 64), "nothing to send")


def test_duplicate_verified_tracking_is_refused() -> None:
    results = all_good() + verified(claim("tracking_number"))
    refused(prepare_send(sendable_dispute(), results, hash_of(all_good())), "tracking number and the carrier")


@pytest.mark.parametrize(
    ("bad", "verdict"),
    [
        (claim("tracking_number", "000"), Verdict.BLOCKED),
        (claim("carrier", "UPS"), Verdict.BLOCKED),
        (Claim(type="tracking_number", value="122533485", source="paypal"), Verdict.FLAGGED),
    ],
)
def test_blocked_or_flagged_shipping_claim_is_refused(bad: Claim, verdict: Verdict) -> None:
    keep = [t for t in GOOD if t != bad.type]
    results = verified(*(claim(t) for t in keep), bad)
    assert results[-1].verdict is verdict
    notes = render_notes(results)
    assert notes is not None  # other claims still render
    refused(prepare_send(sendable_dispute(), results, notes_hash(notes)), "tracking number and the carrier VERIFIED")


def test_refused_when_shipping_claims_are_missing() -> None:
    results = verified(claim("transaction_id"), claim("amount"))
    refused(prepare_send(sendable_dispute(), results, hash_of(results)), "tracking number and the carrier")


def test_flagged_merchant_record_for_other_transaction_is_refused() -> None:
    other = MerchantOrderRecord(transaction_id="OTHER-TXN", tracking_number="122533485", carrier="FEDEX")
    results = verified(*(claim(t) for t in GOOD), record=other)
    assert results[-1].verdict is Verdict.FLAGGED and results[-2].verdict is Verdict.FLAGGED
    refused(prepare_send(sendable_dispute(), results, hash_of(results)), "tracking number and the carrier")


def test_no_blocked_or_flagged_value_reaches_the_payload() -> None:
    results = all_good() + verified(
        claim("amount", {"value": "999.99", "currency_code": "EUR"}),  # BLOCKED
        Claim(type="refund_note", value="BLOCKED-OR-FLAGGED-MARKER", source="paypal"),  # FLAGGED
        Claim(type="tracking_number", value="FLAGGED-TRACKING", source="paypal"),  # FLAGGED: wrong source
    )
    outcome = prepare_send(sendable_dispute(), results, hash_of(all_good()))
    assert isinstance(outcome, SendPlan)
    payload = json.dumps(outcome.evidence.to_payload())
    for leaked in ("999.99", "EUR", "BLOCKED-OR-FLAGGED-MARKER", "FLAGGED-TRACKING"):
        assert leaked not in payload


# Rule 4: carrier list


def test_carrier_list_is_fedex_only() -> None:
    assert ALLOWED_CARRIERS == ("FEDEX",)


def test_verified_carrier_outside_the_list_is_refused() -> None:
    record = MerchantOrderRecord(transaction_id=TXN_ID, tracking_number="122533485", carrier="UPS")
    results = verified(claim("tracking_number"), claim("carrier", "UPS"), record=record)
    assert all(r.verdict is Verdict.VERIFIED for r in results)
    assert render_notes(results) is None  # no shipping sentence for an unlisted carrier
    refused(prepare_send(sendable_dispute(), results, "0" * 64), "carrier is not supported", "FEDEX")


# Rule 5: notes length


def _hand_verified(type_: str, value: Any) -> ClaimResult:
    return ClaimResult(claim=Claim(type=type_, value=value, source=GOOD[type_][0]),
                       verdict=Verdict.VERIFIED, checked_against=GOOD[type_][0], reason="test")


def _with_txn_id(length: int) -> list[ClaimResult]:
    return [_hand_verified("transaction_id", "T" * length),
            _hand_verified("tracking_number", "122533485"), _hand_verified("carrier", "FEDEX")]


def test_notes_at_the_limit_are_sent() -> None:
    base = len(render_notes(_with_txn_id(1)) or "") - 1
    results = _with_txn_id(MAX_NOTES_CHARS - base)
    assert len(render_notes(results) or "") == MAX_NOTES_CHARS
    assert isinstance(prepare_send(sendable_dispute(), results, hash_of(results)), SendPlan)


def test_notes_over_the_limit_are_refused_not_cut() -> None:
    base = len(render_notes(_with_txn_id(1)) or "") - 1
    results = _with_txn_id(MAX_NOTES_CHARS - base + 1)
    refused(prepare_send(sendable_dispute(), results, hash_of(results)), str(MAX_NOTES_CHARS))


# Rule 6: the hash of the text the merchant was shown


@pytest.mark.parametrize(
    "shown",
    ["", "0" * 64, notes_hash("some other text"), "é" * 64, None, 123],
)
def test_refused_when_shown_hash_differs(shown: Any) -> None:
    refused(prepare_send(sendable_dispute(), all_good(), shown), "differs from the one shown")


def test_changed_claims_between_draft_and_approve_are_refused() -> None:
    shown = hash_of(all_good())
    # At approve time the model drops the amount: the text changes, so nothing is sent.
    approve_results = verified(*(claim(t) for t in GOOD if t != "amount"))
    refused(prepare_send(sendable_dispute(), approve_results, shown), "differs from the one shown")


def test_upper_case_hash_is_refused() -> None:
    results = all_good()
    refused(prepare_send(sendable_dispute(), results, hash_of(results).upper()), "differs")


def test_refusal_order_link_first() -> None:
    d = Dispute.model_validate(fixture("dispute_under_review.json"))
    refused(prepare_send(d, [], ""), "does not offer provide-evidence")
