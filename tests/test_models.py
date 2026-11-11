from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from dispute_defender.paypal import Dispute, Evidence, TrackingInfo
from dispute_defender.paypal.models import AccessToken, ActionAck, DisputeList

from .conftest import FAKE_BUYER_VALUES, FAKE_TOKEN, fixture


def test_dispute_parses_fields_used_by_the_app() -> None:
    dispute = Dispute.model_validate(fixture("dispute_inquiry_waiting.json"))
    assert dispute.dispute_id == "PP-R-HBV-10197617"
    assert dispute.status == "WAITING_FOR_SELLER_RESPONSE"
    assert dispute.stage == "INQUIRY"
    assert dispute.reason == "MERCHANDISE_OR_SERVICE_NOT_RECEIVED"
    assert dispute.amount.value == Decimal("10.00")
    assert dispute.amount.currency_code == "USD"
    assert dispute.link_names() == [
        "accept-claim", "escalate", "make-offer", "provide-evidence", "self", "send-message",
    ]


def test_dispute_drops_buyer_details() -> None:
    # Since T-005 the message text is parsed (for the drafter) but must still never
    # appear in model_dump, model_dump_json or repr.
    dispute = Dispute.model_validate(fixture("dispute_inquiry_waiting.json"))
    for shown in (repr(dispute.model_dump()), dispute.model_dump_json(), repr(dispute), str(dispute)):
        for value in FAKE_BUYER_VALUES:
            assert value not in shown
        assert "disputed_transactions" not in shown and "messages" not in shown


def test_dispute_messages_are_readable_by_attribute() -> None:
    dispute = Dispute.model_validate(fixture("dispute_inquiry_waiting.json"))
    assert [(m.posted_by, m.content) for m in dispute.messages] == [("BUYER", "FAKE-BUYER-MESSAGE")]


def test_dispute_message_hides_content() -> None:
    message = Dispute.model_validate(fixture("dispute_inquiry_waiting.json")).messages[0]
    assert "FAKE-BUYER-MESSAGE" not in repr(message)
    assert message.model_dump() == {"posted_by": "BUYER"}


def test_dispute_message_keeps_only_allowlisted_fields() -> None:
    body = fixture("dispute_inquiry_waiting.json")
    body["messages"] = [{"posted_by": "BUYER", "content": "x", "time_posted": "2026-11-09T15:00:00Z",
                         "buyer_email": "fake-buyer@example.invalid"}]
    message = Dispute.model_validate(body).messages[0]
    assert set(type(message).model_fields) == {"posted_by", "content"}
    assert not hasattr(message, "buyer_email")


def test_dispute_without_messages_parses() -> None:
    body = fixture("dispute_inquiry_waiting.json")
    del body["messages"]
    assert Dispute.model_validate(body).messages == []


def test_dispute_parses_transaction_fields_for_verifier() -> None:
    dispute = Dispute.model_validate(fixture("dispute_inquiry_waiting.json"))
    assert len(dispute.transactions) == 1
    txn = dispute.transactions[0]
    assert txn.seller_transaction_id == "54X87564PT289050U"
    assert txn.create_time == datetime(2026, 11, 9, 14, 50, tzinfo=timezone.utc)
    assert txn.gross_amount is not None and txn.gross_amount.value == Decimal("10.00")
    assert txn.gross_amount.currency_code == "USD"
    assert txn.transaction_status == "COMPLETED"
    assert txn.seller_protection_eligible is True


def test_transaction_keeps_no_buyer_fields() -> None:
    txn = Dispute.model_validate(fixture("dispute_inquiry_waiting.json")).transactions[0]
    assert set(txn.model_dump()) == {
        "seller_transaction_id", "create_time", "gross_amount", "transaction_status", "seller_protection_eligible",
    }


def test_missing_transaction_fields_become_none() -> None:
    dispute = Dispute.model_validate(fixture("dispute_chargeback.json"))
    txn = dispute.transactions[0]
    assert (txn.create_time, txn.gross_amount, txn.transaction_status, txn.seller_protection_eligible) == (
        None, None, None, None,
    )


def test_dispute_without_transactions_parses() -> None:
    body = fixture("dispute_inquiry_waiting.json")
    del body["disputed_transactions"]
    assert Dispute.model_validate(body).transactions == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("gross_amount", {"currency_code": "USD", "value": "ten"}),
        ("create_time", "2026-11-09T14:50:00"),  # no timezone
        ("create_time", "yesterday"),
        ("seller_protection_eligible", "true"),
    ],
)
def test_malformed_transaction_field_fails(field: str, value: object) -> None:
    body = fixture("dispute_inquiry_waiting.json")
    body["disputed_transactions"][0][field] = value
    with pytest.raises(ValidationError):
        Dispute.model_validate(body)


@pytest.mark.parametrize(
    ("name", "status", "stage", "links"),
    [
        ("dispute_under_review.json", "UNDER_REVIEW", "INQUIRY", ["self"]),
        ("dispute_chargeback.json", "WAITING_FOR_SELLER_RESPONSE", "CHARGEBACK",
         ["accept-claim", "provide-evidence", "self"]),
    ],
)
def test_other_observed_states(name: str, status: str, stage: str, links: list[str]) -> None:
    dispute = Dispute.model_validate(fixture(name))
    assert (dispute.status, dispute.stage, dispute.link_names()) == (status, stage, links)


@pytest.mark.parametrize("field", ["dispute_id", "status", "dispute_life_cycle_stage", "reason", "dispute_amount"])
def test_dispute_missing_required_field_fails(field: str) -> None:
    body = fixture("dispute_inquiry_waiting.json")
    del body[field]
    with pytest.raises(ValidationError):
        Dispute.model_validate(body)


@pytest.mark.parametrize("value", ["ten", "NaN", "Infinity"])
def test_bad_amount_fails(value: str) -> None:
    body = fixture("dispute_inquiry_waiting.json")
    body["dispute_amount"]["value"] = value
    with pytest.raises(ValidationError):
        Dispute.model_validate(body)


def test_blank_status_fails() -> None:
    body = fixture("dispute_inquiry_waiting.json")
    body["status"] = "  "
    with pytest.raises(ValidationError):
        Dispute.model_validate(body)


def test_list_item_without_amount_parses() -> None:
    items = DisputeList.model_validate(fixture("dispute_list_one.json")).items
    assert len(items) == 1
    assert items[0].amount is None
    assert items[0].stage == "INQUIRY"


def test_has_link_matches_hyphen_and_underscore() -> None:
    dispute = Dispute.model_validate(fixture("dispute_inquiry_waiting.json"))
    assert dispute.has_link("send-message")
    assert dispute.has_link("send_message")
    assert dispute.has_link("PROVIDE_EVIDENCE")
    assert not dispute.has_link("adjudicate")
    assert not dispute.has_link("require-evidence")


def test_action_ack_accepts_empty_body() -> None:
    assert ActionAck.model_validate({}).links == []
    assert ActionAck.model_validate(fixture("action_ack.json")).has_link("self")


def test_access_token_is_secret() -> None:
    token = AccessToken.model_validate(fixture("token.json"))
    assert FAKE_TOKEN not in repr(token)
    assert token.access_token.get_secret_value() == FAKE_TOKEN
    assert "https://uri.paypal.com/services/disputes/update-seller" in token.scopes


def test_evidence_payload_matches_spike_shape() -> None:
    evidence = Evidence(
        tracking_info=[TrackingInfo(carrier_name="FEDEX", tracking_number="122533485")],
        notes="Test evidence with placeholder tracking.",
    )
    assert evidence.to_payload() == {
        "evidence_type": "PROOF_OF_FULFILLMENT",
        "evidence_info": {"tracking_info": [{"carrier_name": "FEDEX", "tracking_number": "122533485"}]},
        "notes": "Test evidence with placeholder tracking.",
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tracking_info": [], "notes": "n"},
        {"tracking_info": [{"carrier_name": "FEDEX", "tracking_number": " "}], "notes": "n"},
        {"tracking_info": [{"carrier_name": "FEDEX", "tracking_number": "1"}], "notes": ""},
        {"evidence_type": "OTHER", "tracking_info": [{"carrier_name": "FEDEX", "tracking_number": "1"}], "notes": "n"},
    ],
)
def test_invalid_evidence_is_rejected(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        Evidence.model_validate(kwargs)
