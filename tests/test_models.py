from __future__ import annotations

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
    dumped = repr(Dispute.model_validate(fixture("dispute_inquiry_waiting.json")).model_dump())
    for value in FAKE_BUYER_VALUES:
        assert value not in dumped
    assert "disputed_transactions" not in dumped and "messages" not in dumped


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
