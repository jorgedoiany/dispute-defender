"""Drafter output schema: what the model must return through the `submit_claims` tool (T-005, ADR-009).

The schema is stricter than `Claim` on purpose. It restricts `type` to the ADR-008
claim types, fixes the allowed `source` per type, forbids extra fields and checks JSON
types. Value formats (decimal strings, YYYY-MM-DD dates, currency codes) are left to
the verifier, which BLOCKS a bad value, so the format rules live in one place.

The shapes follow `dispute_defender/claims/verifier.py`; adapt this file to the
verifier, never the reverse.
"""
from __future__ import annotations

import copy
from typing import Annotated, Any, Literal, Union, get_args

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from dispute_defender.claims import Claim

TOOL_NAME = "submit_claims"
MAX_CLAIMS = 20


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AmountValue(_Strict):
    value: StrictStr = Field(description='Decimal string copied exactly, for example "10.00".')
    currency_code: StrictStr = Field(description="Three-letter currency code, for example USD.")


class TransactionIdClaim(_Strict):
    type: Literal["transaction_id"]
    source: Literal["paypal"]
    value: StrictStr = Field(description="paypal_data.transaction.seller_transaction_id, copied exactly.")


class AmountClaim(_Strict):
    type: Literal["amount"]
    source: Literal["paypal"]
    value: AmountValue = Field(description="paypal_data.transaction.gross_amount, copied exactly.")


class TransactionDateClaim(_Strict):
    type: Literal["transaction_date"]
    source: Literal["paypal"]
    value: StrictStr = Field(description="paypal_data.transaction.transaction_date_utc, a plain YYYY-MM-DD date.")


class SellerProtectionClaim(_Strict):
    type: Literal["seller_protection"]
    source: Literal["paypal"]
    value: StrictBool = Field(description="paypal_data.transaction.seller_protection_eligible (true or false).")


class TrackingNumberClaim(_Strict):
    type: Literal["tracking_number"]
    source: Literal["merchant_record"]
    value: StrictStr = Field(description="merchant_record.tracking_number, copied exactly.")


class CarrierClaim(_Strict):
    type: Literal["carrier"]
    source: Literal["merchant_record"]
    value: StrictStr = Field(description="merchant_record.carrier, copied exactly.")


_CLAIM_MODELS = (
    TransactionIdClaim,
    AmountClaim,
    TransactionDateClaim,
    SellerProtectionClaim,
    TrackingNumberClaim,
    CarrierClaim,
)
DraftClaim = Annotated[Union[_CLAIM_MODELS], Field(discriminator="type")]  # noqa: UP007


class DraftOutput(_Strict):
    """Claims for the merchant's dispute response; each copies one value from paypal_data or merchant_record."""

    # The docstring above is sent to the model as the schema description.
    # Validation is all or nothing: one bad claim rejects the whole output.
    claims: Annotated[list[DraftClaim], Field(min_length=1, max_length=MAX_CLAIMS)]


def _only_arg(model: type[BaseModel], field: str) -> str:
    (value,) = get_args(model.model_fields[field].annotation)
    return value


# Claim type -> the only source the drafter may cite for it. Must match the verifier's rules.
DRAFT_CLAIM_SOURCES: dict[str, str] = {_only_arg(m, "type"): _only_arg(m, "source") for m in _CLAIM_MODELS}


def to_claims(output: DraftOutput) -> list[Claim]:
    """Convert validated drafter output into ADR-008 claims for the verifier."""
    return [Claim(**claim.model_dump()) for claim in output.claims]


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            return _inline(copy.deepcopy(defs[ref.removeprefix("#/$defs/")]), defs)
        return {
            key: _inline(value, defs)
            for key, value in node.items()
            if key not in ("$defs", "discriminator", "title")
        }
    if isinstance(node, list):
        return [_inline(item, defs) for item in node]
    return node


def tool_input_schema() -> dict[str, Any]:
    """JSON schema of DraftOutput with every $ref inlined (and no $defs or discriminator)."""
    schema = DraftOutput.model_json_schema()
    return _inline(schema, schema.get("$defs", {}))


def tool_spec() -> dict[str, Any]:
    """The Bedrock Converse `toolSpec` entry for `submit_claims`."""
    return {
        "toolSpec": {
            "name": TOOL_NAME,
            "description": (
                "Submit the factual claims for the merchant's dispute response. "
                "Each claim copies one value from paypal_data or merchant_record."
            ),
            "inputSchema": {"json": tool_input_schema()},
        }
    }
