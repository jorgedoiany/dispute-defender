"""Replay data loader (T-010, ADR-012).

`data/replay.json` holds hand-written, SIMULATED disputes and model outputs rebuilt from
claims recorded in the T-007 live run on simulated scenarios. The loader refuses a file
that is not labelled `"simulated": true`, a dispute without a source label, a dispute
that does not pass the app's own `Dispute` model, a model output that does not pass the
drafter's `DraftOutput` schema, and duplicate dispute or transaction IDs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from dispute_defender.drafter.schema import DraftOutput
from dispute_defender.paypal import Dispute, check_dispute_id

DATA_PATH = Path(__file__).parent / "data" / "replay.json"

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Source(_Strict):
    """Where each part of a replay dispute comes from. Shown on the page."""

    dispute: Text
    model_output: Text | None
    adapted: Text | None
    injected: Text | None


class Hint(_Strict):
    """What to type on the dispute page so the merchant record matches the recorded output."""

    tracking_number: Text
    carrier: Text


class ReplayDispute(_Strict):
    title: Text
    source: Source
    hint: Hint | None
    provenance: dict[str, Any]
    dispute: dict[str, Any]
    after_send: dict[str, Any]
    model_output: dict[str, Any] | None

    @model_validator(mode="after")
    def _check(self) -> ReplayDispute:
        parsed = Dispute.model_validate(self.dispute)
        check_dispute_id(parsed.dispute_id)
        Dispute.model_validate({**self.dispute, **self.after_send})
        if self.model_output is not None:
            DraftOutput.model_validate(self.model_output)
            if self.source.model_output is None:
                raise ValueError("a model output needs a source label")
            if len(parsed.transactions) != 1 or not parsed.transactions[0].seller_transaction_id:
                raise ValueError("a dispute with a model output needs exactly one transaction with an ID")
        return self

    @property
    def dispute_id(self) -> str:
        return str(self.dispute["dispute_id"])

    @property
    def transaction_id(self) -> str | None:
        txns = self.dispute.get("disputed_transactions") or []
        return txns[0].get("seller_transaction_id") if len(txns) == 1 else None


class ReplayData(_Strict):
    simulated: Literal[True]
    notice: Text
    recorded_model_id: Text
    disputes: list[ReplayDispute] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> ReplayData:
        ids = [d.dispute_id for d in self.disputes]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate dispute IDs")
        txns = [d.transaction_id for d in self.disputes if d.model_output is not None]
        if len(set(txns)) != len(txns):
            raise ValueError("duplicate transaction IDs among disputes with a model output")
        return self

    def by_id(self, dispute_id: str) -> ReplayDispute | None:
        return next((d for d in self.disputes if d.dispute_id == dispute_id), None)


def load_replay(path: Path = DATA_PATH) -> ReplayData:
    """Load and validate the replay data. Raises ValueError (or pydantic's ValidationError)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("simulated") is not True:
        raise ValueError("replay data must be labelled \"simulated\": true")
    return ReplayData.model_validate(raw)
