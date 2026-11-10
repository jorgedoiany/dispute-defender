"""Claim schema and verification result types (T-004, ADR-008)."""
from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

SOURCE_PAYPAL = "paypal"
SOURCE_MERCHANT_RECORD = "merchant_record"
Source = Literal["paypal", "merchant_record"]


class Claim(BaseModel):
    """One factual claim in a drafted response.

    `type` and `source` are plain strings on purpose: an unknown type or a missing or
    unknown source reaches the verifier and is FLAGGED instead of failing the whole draft.
    `value` is any JSON value; each rule checks its shape and BLOCKS an invalid one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str
    value: Any
    source: str | None = None


class MerchantOrderRecord(BaseModel):
    """The merchant's own order record, passed in by the caller. Not PayPal data.

    `transaction_id`, if given, must equal the dispute's seller_transaction_id; otherwise
    merchant-record claims are FLAGGED because the record may be for another order.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    transaction_id: NonEmpty | None = None
    tracking_number: NonEmpty | None = None
    carrier: NonEmpty | None = None


class Verdict(StrEnum):
    VERIFIED = "VERIFIED"  # matches the source data
    FLAGGED = "FLAGGED"  # could not be checked: no data, no or wrong source, unsupported type
    BLOCKED = "BLOCKED"  # contradicts the source data, or the value is invalid


class ClaimResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim: Claim
    verdict: Verdict
    # The source this claim type is checked against; None if the type or source was rejected.
    checked_against: Source | None
    reason: str
