"""Pydantic models for the PayPal Disputes API.

Response models hold only the fields the app uses. Everything else, including any
buyer details, is ignored at the boundary and never enters app objects.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr, StrictBool, StringConstraints

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# Values observed in the T-002 spike. Fields stay plain strings so an unseen value
# does not break a read; compare against these constants instead.
STATUS_WAITING_FOR_SELLER = "WAITING_FOR_SELLER_RESPONSE"
STATUS_WAITING_FOR_BUYER = "WAITING_FOR_BUYER_RESPONSE"
STATUS_UNDER_REVIEW = "UNDER_REVIEW"
STAGE_INQUIRY = "INQUIRY"
STAGE_CHARGEBACK = "CHARGEBACK"
REASON_NOT_RECEIVED = "MERCHANDISE_OR_SERVICE_NOT_RECEIVED"


class _Response(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)


def _norm_rel(rel: str) -> str:
    return rel.strip().lower().replace("_", "-")


class Money(_Response):
    currency_code: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    value: Annotated[Decimal, Field(allow_inf_nan=False)]


class Link(_Response):
    href: NonEmpty
    rel: NonEmpty
    method: str | None = None


class _HasLinks(_Response):
    links: list[Link] = Field(default_factory=list)

    def has_link(self, rel: str) -> bool:
        """True if PayPal offers this link. `send_message` and `send-message` match."""
        wanted = _norm_rel(rel)
        return any(_norm_rel(link.rel) == wanted for link in self.links)

    def link_names(self) -> list[str]:
        return sorted({_norm_rel(link.rel) for link in self.links})


class DisputedTransaction(_Response):
    """Seller-side fields of one entry in `disputed_transactions`, used by the claim verifier (T-004).

    Every field is optional so a missing one leads to a FLAGGED claim, not a failed read.
    A field that is present but malformed still fails validation. Buyer fields
    (`buyer`, `buyer_transaction_id`) and everything else are dropped here.
    """

    seller_transaction_id: NonEmpty | None = None
    create_time: AwareDatetime | None = None
    gross_amount: Money | None = None
    transaction_status: str | None = None  # kept for later use; no verifier rule reads it yet
    seller_protection_eligible: StrictBool | None = None


class DisputeMessage(_Response):
    """One entry of `messages[]`, read only for the drafter prompt (T-005, ADR-009).

    `content` is free text, usually written by the buyer: untrusted data that may hold
    personal details or instructions. It is kept out of repr and model_dump so it is
    never printed or logged by accident; read it only through the attribute.
    """

    posted_by: str | None = None
    content: str | None = Field(default=None, exclude=True, repr=False)


class Dispute(_HasLinks):
    """One dispute as returned by GET /v1/customer/disputes/{id}."""

    dispute_id: NonEmpty
    status: NonEmpty
    stage: NonEmpty = Field(alias="dispute_life_cycle_stage")
    reason: NonEmpty
    amount: Money = Field(alias="dispute_amount")
    transactions: list[DisputedTransaction] = Field(default_factory=list, alias="disputed_transactions")
    # Untrusted free text; excluded from repr and model_dump (see DisputeMessage).
    messages: list[DisputeMessage] = Field(default_factory=list, exclude=True, repr=False)


class DisputeListItem(_HasLinks):
    """One item of GET /v1/customer/disputes. Amount is optional: T-002 did not confirm it there."""

    dispute_id: NonEmpty
    status: NonEmpty
    stage: NonEmpty = Field(alias="dispute_life_cycle_stage")
    reason: NonEmpty
    amount: Money | None = Field(default=None, alias="dispute_amount")


class DisputeList(_Response):
    items: list[DisputeListItem] = Field(default_factory=list)


class ActionAck(_HasLinks):
    """Response to a dispute action (send-message, provide-evidence)."""


class AccessToken(_Response):
    access_token: SecretStr
    expires_in: Annotated[int, Field(gt=0)]
    scope: str = ""

    @property
    def scopes(self) -> list[str]:
        return self.scope.split()


# Request side: only the evidence shape PayPal accepted in T-002 (no files).


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TrackingInfo(_Request):
    carrier_name: NonEmpty
    tracking_number: NonEmpty


class Evidence(_Request):
    evidence_type: Literal["PROOF_OF_FULFILLMENT"] = "PROOF_OF_FULFILLMENT"
    tracking_info: Annotated[list[TrackingInfo], Field(min_length=1)]
    notes: NonEmpty

    def to_payload(self) -> dict[str, object]:
        return {
            "evidence_type": self.evidence_type,
            "evidence_info": {"tracking_info": [item.model_dump() for item in self.tracking_info]},
            "notes": self.notes,
        }
