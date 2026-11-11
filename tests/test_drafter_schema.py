"""Offline tests for the drafter output schema and tool spec (T-005)."""
from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from dispute_defender.claims import MerchantOrderRecord, Verdict, verify_claims
from dispute_defender.claims.verifier import RULES
from dispute_defender.drafter import (
    DRAFT_CLAIM_SOURCES,
    MAX_CLAIMS,
    TOOL_NAME,
    DraftOutput,
    to_claims,
    tool_input_schema,
    tool_spec,
)
from dispute_defender.paypal import Dispute

from .conftest import fixture

TXN_ID = "54X87564PT289050U"
RECORD = MerchantOrderRecord(transaction_id=TXN_ID, tracking_number="122533485", carrier="FedEx")


def valid_output() -> dict[str, Any]:
    return {
        "claims": [
            {"type": "transaction_id", "source": "paypal", "value": TXN_ID},
            {"type": "amount", "source": "paypal", "value": {"value": "10.00", "currency_code": "USD"}},
            {"type": "transaction_date", "source": "paypal", "value": "2026-11-09"},
            {"type": "seller_protection", "source": "paypal", "value": True},
            {"type": "tracking_number", "source": "merchant_record", "value": "122533485"},
            {"type": "carrier", "source": "merchant_record", "value": "FedEx"},
        ]
    }


def with_claim(claim: dict[str, Any]) -> dict[str, Any]:
    return {"claims": [claim]}


def walk(node: Any) -> list[Any]:
    found = [node]
    if isinstance(node, dict):
        for value in node.values():
            found += walk(value)
    elif isinstance(node, list):
        for item in node:
            found += walk(item)
    return found


# Valid output


def test_valid_output_converts_to_claims_that_verify() -> None:
    claims = to_claims(DraftOutput.model_validate(valid_output()))
    assert [c.type for c in claims] == [c["type"] for c in valid_output()["claims"]]
    assert claims[1].value == {"value": "10.00", "currency_code": "USD"}
    dispute = Dispute.model_validate(fixture("dispute_inquiry_waiting.json"))
    results = verify_claims(dispute, claims, RECORD)
    assert [r.verdict for r in results] == [Verdict.VERIFIED] * 6, [r.reason for r in results]


def test_drafter_types_and_sources_match_the_verifier() -> None:
    assert DRAFT_CLAIM_SOURCES == {name: rule.source for name, rule in RULES.items()}


# Rejected at the schema boundary (the whole output)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"claims": "not a list"},
        {"claims": []},
        {"claims": [{"type": "transaction_id", "source": "paypal", "value": TXN_ID}] * (MAX_CLAIMS + 1)},
        {"claims": valid_output()["claims"], "note": "extra top-level field"},
        with_claim({"type": "delivery_signature", "source": "paypal", "value": "x"}),
        with_claim({"type": "amount", "source": "paypal", "value": {"value": "10.00", "currency_code": "USD"},
                    "confidence": 0.9}),
        with_claim({"type": "amount", "source": "paypal",
                    "value": {"value": "10.00", "currency_code": "USD", "note": "x"}}),
        with_claim({"type": "amount", "source": "paypal", "value": {"value": 10.0, "currency_code": "USD"}}),
        with_claim({"type": "amount", "source": "paypal", "value": {"value": 10, "currency_code": "USD"}}),
        with_claim({"type": "amount", "source": "paypal", "value": "10.00 USD"}),
        with_claim({"type": "seller_protection", "source": "paypal", "value": "true"}),
        with_claim({"type": "seller_protection", "source": "paypal", "value": 1}),
        with_claim({"type": "transaction_id", "source": "paypal", "value": 123}),
        with_claim({"type": "transaction_id", "source": "paypal"}),
        with_claim({"type": "transaction_id", "value": TXN_ID}),
        with_claim({"type": "tracking_number", "source": "paypal", "value": "122533485"}),
        with_claim({"type": "carrier", "source": "paypal", "value": "FedEx"}),
        with_claim({"type": "amount", "source": "merchant_record",
                    "value": {"value": "10.00", "currency_code": "USD"}}),
        with_claim({"type": "transaction_id", "source": "PayPal", "value": TXN_ID}),
    ],
    ids=[
        "missing-claims", "claims-not-list", "empty-list", "too-many-claims", "extra-top-level",
        "unknown-type", "extra-claim-field", "extra-amount-field", "amount-float", "amount-int",
        "amount-string", "bool-as-string", "bool-as-int", "id-as-int", "missing-source",
        "missing-value-source", "tracking-from-paypal", "carrier-from-paypal", "amount-from-record",
        "source-wrong-case",
    ],
)
def test_invalid_output_is_rejected(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DraftOutput.model_validate(body)


def test_one_bad_claim_rejects_the_whole_output() -> None:
    body = valid_output()
    body["claims"].append({"type": "delivery_signature", "source": "paypal", "value": "x"})
    with pytest.raises(ValidationError):
        DraftOutput.model_validate(body)


# Format problems pass the schema and are BLOCKED by the verifier (one place for format rules)


@pytest.mark.parametrize(
    "claim",
    [
        {"type": "amount", "source": "paypal", "value": {"value": "ten", "currency_code": "USD"}},
        {"type": "amount", "source": "paypal", "value": {"value": "10.00", "currency_code": "usd"}},
        {"type": "transaction_date", "source": "paypal", "value": "11/09/2026"},
        {"type": "transaction_date", "source": "paypal", "value": "2026-11-09 (UTC)"},
        {"type": "transaction_id", "source": "paypal", "value": ""},
    ],
    ids=["amount-word", "currency-lowercase", "date-us-format", "date-with-suffix", "empty-id"],
)
def test_format_errors_pass_schema_and_are_blocked_by_verifier(claim: dict[str, Any]) -> None:
    claims = to_claims(DraftOutput.model_validate(with_claim(claim)))
    dispute = Dispute.model_validate(fixture("dispute_inquiry_waiting.json"))
    (result,) = verify_claims(dispute, claims, RECORD)
    assert result.verdict is Verdict.BLOCKED
    assert result.reason.startswith("invalid value:")


# Tool spec


def test_tool_schema_has_no_refs_or_defs() -> None:
    text = json.dumps(tool_input_schema())
    for keyword in ("$ref", "$defs", "discriminator"):
        assert keyword not in text


def test_tool_schema_restricts_types_and_sources() -> None:
    claims_schema = tool_input_schema()["properties"]["claims"]
    assert claims_schema["minItems"] == 1 and claims_schema["maxItems"] == MAX_CLAIMS
    branches = claims_schema["items"]["oneOf"]
    pairs = {(b["properties"]["type"]["const"], b["properties"]["source"]["const"]) for b in branches}
    assert pairs == set(DRAFT_CLAIM_SOURCES.items())
    for node in walk(tool_input_schema()):
        if isinstance(node, dict) and node.get("type") == "object":
            assert node.get("additionalProperties") is False


def test_tool_spec_shape() -> None:
    spec = tool_spec()["toolSpec"]
    assert spec["name"] == TOOL_NAME
    assert spec["inputSchema"]["json"] == tool_input_schema()
    assert spec["description"]
